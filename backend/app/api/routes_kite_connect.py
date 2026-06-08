from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.config import settings
from app.models import User
from app.schemas import BrokerAccountResponse
import app.services.kite_connect as kite_service


router = APIRouter(tags=["kite-connect"], prefix="/kite_connect")


# ---------------------------------------------------------------------------
# Auth / session routes
# ---------------------------------------------------------------------------

@router.get("/")
def login():
    """Return the Kite login redirect URL."""
    return {"redirect_url": kite_service.get_login_url()}


@router.get("/callback")
def callback(request_token: str, db: Session = Depends(get_db)):
    """
    Handle Kite OAuth callback.
    - Generates a session and stores the access token.
    - Upserts the broker account details in the DB.
    """
    try:
        session_data = kite_service.generate_session(request_token)
        return RedirectResponse(
            url=f"{settings.frontend_base_url}/dashboard?kite_connected=true"
        )
    except Exception as e:
        print(f"Kite login callback error: {e}")
        return RedirectResponse(
            url=f"{settings.frontend_base_url}/dashboard?kite_error={str(e)}"
        )


@router.get("/status")
def status():
    """Return Kite connection status."""
    return kite_service.get_status()


@router.post("/disconnect")
def disconnect():
    """Clear the Kite access token."""
    try:
        return kite_service.disconnect()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Data routes
# ---------------------------------------------------------------------------

@router.get("/profile")
def profile(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetch the Kite user profile."""
    try:
        user_profile = kite_service.get_profile()
        # upsert broker account
        kite_service.upsert_broker_account(user_profile, db, current_user)
        return {"data": user_profile}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to fetch profile: {str(e)}")


@router.get("/orders")
def orders(current_user: User = Depends(get_current_user)):
    """Fetch all Kite orders."""
    try:
        user_orders = kite_service.get_orders()
        return {"data": user_orders}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to fetch orders: {str(e)}")


@router.get("/trades")
def trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Fetch all trades from Kite and persist them to the local trades table.
    Returns the raw trade data along with the count of newly inserted records.
    """
    try:
        user_trades = kite_service.get_trades()
        profile = kite_service.get_profile()
        inserted = kite_service.upsert_trades_to_db(user_trades,profile, db, current_user)
        return {
            "data": user_trades,
            "inserted_count": inserted,
            "message": f"{inserted} new trade(s) saved to the database.",
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to fetch trades: {str(e)}")


# ---------------------------------------------------------------------------
# Broker account routes
# ---------------------------------------------------------------------------

@router.get("/broker-account", response_model=BrokerAccountResponse)
def get_broker_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Return the stored broker account details for the currently connected user.
    Requires a valid Kite session.
    """
    from app.models import BrokerAccount

    status_info = kite_service.get_status()
    if not status_info.get("connected"):
        raise HTTPException(status_code=401, detail="Not connected to Kite. Please login first.")

    try:
        profile = kite_service.get_profile()
        user_id = str(profile.get("user_id", ""))
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Failed to fetch profile: {str(e)}")

    account = db.query(BrokerAccount).filter(BrokerAccount.broker_user_id == user_id).first()
    if not account:
        # Auto-upsert if not yet in DB
        account = kite_service.upsert_broker_account(profile, db, current_user)

    return account


@router.post("/broker-account/sync", response_model=BrokerAccountResponse)
def sync_broker_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Sync the broker account details from Kite profile into the database.
    Creates the record if it doesn't exist, updates it otherwise.
    """
    status_info = kite_service.get_status()
    if not status_info.get("connected"):
        raise HTTPException(status_code=401, detail="Not connected to Kite. Please login first.")

    try:
        profile = kite_service.get_profile()
        account = kite_service.upsert_broker_account(profile, db, current_user)
        return account
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to sync broker account: {str(e)}")