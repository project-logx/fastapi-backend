from __future__ import annotations

from sqlalchemy import desc
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Trade, TradeStatus
from app.services.serialization import serialize_trade


router = APIRouter(tags=["journeys"])


@router.get("/journeys")
def list_journeys(symbol: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    safe_limit = max(1, min(limit, 500))
    query = db.query(Trade).filter(Trade.status == TradeStatus.COMPLETE.value)
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())

    rows = query.order_by(desc(Trade.closed_at), desc(Trade.id)).limit(safe_limit).all()
    return {"data": [serialize_trade(item, include_nodes=False) for item in rows], "meta": {"count": len(rows)}}


@router.get("/journeys/{journey_id}")
def get_journey(journey_id: int, db: Session = Depends(get_db)) -> dict:
    trade = db.query(Trade).filter(Trade.id == journey_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Journey not found")
    if trade.status != TradeStatus.COMPLETE.value:
        raise HTTPException(status_code=409, detail="Trade is not complete yet")
    return {"data": serialize_trade(trade, include_nodes=True)}
