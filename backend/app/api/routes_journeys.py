from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models import Trade, TradeStatus
from app.services.journey_aggregation import (
    collect_journey_nodes,
    list_primary_journey_trades,
    related_trades_for_journey,
)
from app.services.serialization import serialize_journey, serialize_trade


router = APIRouter(tags=["journeys"])


def _build_journey_payload(db: Session, primary_trade: Trade) -> dict:
    related_trades = related_trades_for_journey(db, primary_trade)
    journey_nodes = collect_journey_nodes(related_trades)
    return serialize_journey(
        primary_trade=primary_trade,
        related_trades=related_trades,
        journey_nodes=journey_nodes,
    )


@router.get("/journeys")
def list_journeys(symbol: str | None = None, limit: int = 100, db: Session = Depends(get_db), current_user=Depends(get_current_user)) -> dict:
    rows = list_primary_journey_trades(db, symbol=symbol, limit=limit, current_user=current_user)
    return {"data": [serialize_trade(item, include_nodes=False) for item in rows], "meta": {"count": len(rows)}}


@router.get("/journeys/{journey_id}")
def get_journey(journey_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)) -> dict:
    trade = db.query(Trade).filter(Trade.id == journey_id,Trade.user_id == current_user.id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Journey not found")
    if trade.status != TradeStatus.COMPLETE.value:
        raise HTTPException(status_code=409, detail="Trade is not complete yet")

    return {"data": _build_journey_payload(db, trade)}
