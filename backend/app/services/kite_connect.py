from __future__ import annotations
from app.models import TradeStatus

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session
import kiteconnect as kiteconnect_lib

load_dotenv()
from app.models import User, BrokerAccount

# ---------------------------------------------------------------------------
# Per-user KiteConnect session manager
# ---------------------------------------------------------------------------

KITE_API_KEY = os.getenv("KITE_API_KEY")
STATE_SECRET = os.getenv("SECRET_KEY", "change-me")
# State tokens are valid for 10 minutes (enough for the OAuth round-trip)
STATE_TTL_SECONDS = 600


class KiteSessionManager:
    """
    Manages one KiteConnect instance per user.

    In-memory dict: { user_id (int) -> KiteConnect instance }
    On first access for a user, if a valid access_token exists in the
    broker_accounts table, the session is automatically restored.

    Also tracks pending OAuth flows so the callback can identify which
    user initiated the login (since Zerodha doesn't echo back state params).
    """

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._sessions: dict[int, kiteconnect_lib.KiteConnect] = {}
        # Tracks pending OAuth: { user_id -> timestamp }
        # Used to identify the most recent user who initiated login
        self._pending_auth: dict[int, float] = {}

    def get_kite(self, user_id: int) -> kiteconnect_lib.KiteConnect:
        """Return (or create) the KiteConnect instance for `user_id`."""
        if user_id not in self._sessions:
            self._sessions[user_id] = kiteconnect_lib.KiteConnect(
                api_key=self._api_key
            )
        return self._sessions[user_id]

    def set_access_token(self, user_id: int, token: str) -> None:
        kite = self.get_kite(user_id)
        kite.set_access_token(token)

    def remove(self, user_id: int) -> None:
        """Remove a user's session from the in-memory store."""
        inst = self._sessions.pop(user_id, None)
        if inst and hasattr(inst, "access_token"):
            inst.access_token = None

    def store_pending_auth(self, user_id: int) -> None:
        """Record that this user initiated a Kite OAuth flow."""
        self._pending_auth[user_id] = time.time()
        # Clean up expired entries (older than 10 minutes)
        cutoff = time.time() - STATE_TTL_SECONDS
        expired = [uid for uid, ts in self._pending_auth.items() if ts < cutoff]
        for uid in expired:
            self._pending_auth.pop(uid, None)

    def retrieve_pending_auth(self) -> int | None:
        """
        Return the user_id of the most recent pending OAuth flow.
        Removes the entry after retrieval (one-time use).
        Returns None if no valid pending auth exists.
        """
        if not self._pending_auth:
            return None
        cutoff = time.time() - STATE_TTL_SECONDS
        # Find the most recent non-expired entry
        valid = {uid: ts for uid, ts in self._pending_auth.items() if ts >= cutoff}
        if not valid:
            return None
        # Get the most recently initiated auth
        user_id = max(valid, key=valid.get)  # type: ignore
        del self._pending_auth[user_id]
        return user_id


# Module-level singleton manager (NOT a singleton kite instance)
_manager = KiteSessionManager(api_key=KITE_API_KEY)


def _get_kite_for_user(user_id: int, db: Session) -> kiteconnect_lib.KiteConnect:
    """
    Return the KiteConnect instance for `user_id`, restoring the session
    from the database if the in-memory instance has no access_token yet.
    """
    kite = _manager.get_kite(user_id)

    # If already authenticated in-memory, just return
    if getattr(kite, "access_token", None):
        return kite

    # Try to restore from the DB
    account = (
        db.query(BrokerAccount)
        .filter(BrokerAccount.user_id == user_id, BrokerAccount.is_active == True)
        .order_by(BrokerAccount.connected_at.desc())
        .first()
    )
    if account and account.access_token:
        kite.set_access_token(account.access_token)

    return kite


# ---------------------------------------------------------------------------
# Signed state token helpers (for OAuth callback identification)
# ---------------------------------------------------------------------------

def _sign(payload: str) -> str:
    """HMAC-SHA256 signature of a payload string."""
    return hmac.new(
        STATE_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def encode_state(user_id: int) -> str:
    """
    Create a signed, time-limited state token encoding the user_id.
    Format: base64(json({"uid": <id>, "ts": <epoch>})) + "." + signature
    """
    payload = json.dumps({"uid": user_id, "ts": int(time.time())})
    sig = _sign(payload)
    return f"{payload}|{sig}"


def decode_state(state: str) -> int | None:
    """
    Decode and verify a state token. Returns user_id or None if invalid/expired.
    """
    try:
        payload, sig = state.rsplit("|", 1)
        # Verify signature
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        data = json.loads(payload)
        # Verify TTL
        if int(time.time()) - data["ts"] > STATE_TTL_SECONDS:
            return None
        return int(data["uid"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Auth / session helpers
# ---------------------------------------------------------------------------

def get_login_url(user_id: int) -> str:
    """
    Return the Kite login redirect URL.
    Also records the pending OAuth flow so the callback can identify the user
    (Zerodha does not echo back custom query parameters or state).
    """
    _manager.store_pending_auth(user_id)
    kite = _manager.get_kite(user_id)
    return kite.login_url()


def get_pending_auth_user() -> int | None:
    """
    Retrieve the user_id of the most recent pending Kite OAuth flow.
    One-time use: the entry is removed after retrieval.
    """
    return _manager.retrieve_pending_auth()


def generate_session(request_token: str, user_id: int, db: Session) -> dict:
    """
    Exchange request_token for an access_token and store it:
    - In the per-user KiteConnect instance (in-memory)
    - In the broker_accounts table (persistent)
    """
    kite = _manager.get_kite(user_id)
    api_secret = os.getenv("KITE_API_SECRET")
    data = kite.generate_session(request_token, api_secret=api_secret)
    kite.set_access_token(data["access_token"])

    # Persist access token to DB via upsert_broker_account
    # (called separately in the callback route after this)
    return data


def set_access_token(user_id: int, token: str) -> None:
    _manager.set_access_token(user_id, token)


def get_status(user_id: int, db: Session) -> dict:
    """Return connection status for a specific user."""
    kite = _get_kite_for_user(user_id, db)
    if not getattr(kite, "access_token", None):
        return {"connected": False}
    try:
        kite.profile()
        return {"connected": True}
    except Exception:
        return {"connected": False}


def disconnect(user_id: int, db: Session) -> dict:
    """Clear the user's access token from memory and DB."""
    _manager.remove(user_id)

    # Also mark inactive in DB
    account = (
        db.query(BrokerAccount)
        .filter(BrokerAccount.user_id == user_id, BrokerAccount.is_active == True)
        .first()
    )
    if account:
        account.access_token = None
        account.is_active = False
        db.commit()

    return {"connected": False, "message": "Disconnected successfully"}


# ---------------------------------------------------------------------------
# Data fetchers (per-user)
# ---------------------------------------------------------------------------

def get_profile(user_id: int, db: Session) -> dict:
    """Fetch and return the Kite user profile for a specific user."""
    kite = _get_kite_for_user(user_id, db)
    return kite.profile()


def get_orders(user_id: int, db: Session) -> list[dict]:
    """Fetch and return all orders from Kite for a specific user."""
    kite = _get_kite_for_user(user_id, db)
    return kite.orders()


def get_trades(user_id: int, db: Session) -> list[dict]:
    """Fetch and return all trades from Kite for a specific user."""
    kite = _get_kite_for_user(user_id, db)
    return kite.trades()


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

def upsert_trades_to_db(trades: list[dict[str, Any]], profile: dict[str, Any], db: Session, current_user) -> int:
    """
    Persist trades fetched from Kite into the local `trades` table.

    Kite trade fields mapped → Trade model columns:
      tradingsymbol  → symbol
      product        → product
      transaction_type (BUY/SELL) → direction
      quantity       → quantity
      average_price  → entry_price (for BUY) / exit_price (for SELL)
      pnl            → pnl  (if available)
      trade_id       → source_open_event (used as external reference)
      fill_timestamp → opened_at

    Trades are de-duplicated by `source_open_event` (kite trade_id).
    Returns the count of newly inserted trades.
    """
    from app.models import Trade  # avoid circular imports at module level

    if not trades:
        return 0

    inserted = 0
    for t in trades:
        trade_id = str(t.get("trade_id", ""))
        if not trade_id:
            continue

        existing = (
            db.query(Trade).filter(Trade.source_open_event == trade_id).first()
        )
        if existing:
            continue  # already stored

        direction = (t.get("transaction_type") or "BUY").upper()
        fill_ts_raw = t.get("fill_timestamp") or t.get("order_timestamp")
        if isinstance(fill_ts_raw, str):
            try:
                fill_ts = datetime.fromisoformat(fill_ts_raw)
            except ValueError:
                fill_ts = datetime.now(timezone.utc)
        elif isinstance(fill_ts_raw, datetime):
            fill_ts = fill_ts_raw
        else:
            fill_ts = datetime.now(timezone.utc)

        if fill_ts.tzinfo is None:
            fill_ts = fill_ts.replace(tzinfo=timezone.utc)

        account_id = db.query(BrokerAccount).filter(BrokerAccount.user_id == current_user.id).first().id

        trade = Trade(
            user_id=current_user.id,
            account_id=account_id,
            trade_id=trade_id,
            symbol=t.get("tradingsymbol", "UNKNOWN"),
            product=t.get("product", "MIS"),
            direction=direction,
            quantity=int(t.get("quantity", 0)),
            instrument_token=int(t.get("instrument_token", 0)),
            entry_price=float(t.get("average_price", 0)) if direction == "BUY" else None,
            exit_price=float(t.get("average_price", 0)) if direction == "SELL" else None,
            pnl=float(t.get("pnl")) if t.get("pnl") is not None else None,
            status=TradeStatus.PENDING_ENTRY.value if direction == "BUY" else TradeStatus.PENDING_EXIT.value,
            source_open_event=trade_id,
            opened_at=fill_ts,
        )
        db.add(trade)
        inserted += 1

    db.commit()
    return inserted


def upsert_broker_account(profile: dict[str, Any], db: Session, current_user: User, access_token: str | None = None):
    """
    Create or update a BrokerAccount record based on the Kite profile.
    Returns the BrokerAccount ORM object.
    
    `access_token` can be passed explicitly (e.g. after generate_session).
    If not provided, it tries to read from the user's in-memory kite instance.
    """
    from app.models import BrokerAccount  # avoid circular imports

    user_id = str(profile.get("user_id", ""))
    # Query by broker_user_id alone — it has a unique index in the DB
    existing = (
        db.query(BrokerAccount).filter(BrokerAccount.broker_user_id == user_id, BrokerAccount.user_id == current_user.id).first()
    )

    # Determine the access token to store
    if access_token is None:
        kite = _manager.get_kite(current_user.id)
        access_token = getattr(kite, "access_token", None)

    if existing:
        existing.user_id = current_user.id
        existing.user_name = profile.get("user_name")
        existing.email = profile.get("email")
        existing.broker = profile.get("broker", "zerodha")
        existing.access_token = access_token
        existing.is_active = True
        existing.connected_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        return existing

    account = BrokerAccount(
        user_id=current_user.id,
        broker_user_id=user_id,
        user_name=profile.get("user_name"),
        email=profile.get("email"),
        broker=profile.get("broker", "zerodha"),
        access_token=access_token,
        is_active=True,
        connected_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account
