from __future__ import annotations
from app.models import TradeStatus

import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session
import kiteconnect as kiteconnect_lib

load_dotenv()
from app.models import User, BrokerAccount

# ---------------------------------------------------------------------------
# Singleton KiteConnect instance
# ---------------------------------------------------------------------------

kite = kiteconnect_lib.KiteConnect(api_key=os.getenv("KITE_API_KEY"))


# ---------------------------------------------------------------------------
# Auth / session helpers
# ---------------------------------------------------------------------------

def get_login_url() -> str:
    """Return the Kite login redirect URL."""
    return kite.login_url()


def generate_session(request_token: str) -> dict:
    """Exchange request_token for an access_token and set it on the kite instance."""
    api_secret = os.getenv("KITE_API_SECRET")
    data = kite.generate_session(request_token, api_secret=api_secret)
    kite.set_access_token(data["access_token"])
    return data


def set_access_token(token: str) -> None:
    kite.set_access_token(token)


def get_status() -> dict:
    """Return connection status by attempting a profile call."""
    if not getattr(kite, "access_token", None):
        return {"connected": False}
    try:
        kite.profile()
        return {"connected": True}
    except Exception:
        return {"connected": False}


def disconnect() -> dict:
    """Clear the stored access token."""
    if hasattr(kite, "access_token"):
        kite.access_token = None
    return {"connected": False, "message": "Disconnected successfully"}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def get_profile() -> dict:
    """Fetch and return the Kite user profile."""
    return kite.profile()


def get_orders() -> list[dict]:
    """Fetch and return all orders from Kite."""
    return kite.orders()


def get_trades() -> list[dict]:
    """Fetch and return all trades from Kite."""
    return kite.trades()


# ---------------------------------------------------------------------------
# DB upsert helpers
# ---------------------------------------------------------------------------

def upsert_trades_to_db(trades: list[dict[str, Any]],profile: dict[str, Any], db: Session,current_user) -> int:
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


def upsert_broker_account(profile: dict[str, Any], db: Session,current_user: User):
    """
    Create or update a BrokerAccount record based on the Kite profile.
    Returns the BrokerAccount ORM object.
    """
    from app.models import BrokerAccount  # avoid circular imports

    user_id = str(profile.get("user_id", ""))
    existing = (
        db.query(BrokerAccount).filter(BrokerAccount.broker_user_id == user_id, BrokerAccount.user_id == current_user.id).first()
    )

    access_token = getattr(kite, "access_token", None)

    if existing:
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
