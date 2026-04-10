from __future__ import annotations

import shutil
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models import Attachment, CustomTag, MockEvent, NodeCustomTag, PositionState, Trade, TradeNode
from app.schemas import MockBatchRequest, MockEntryRequest, MockExitRequest
from app.services.mock_ingestion import build_entry_payload, build_exit_payload, process_payload


router = APIRouter(tags=["mock"])


def _event_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def _timestamp(raw: datetime | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC)
    return raw.astimezone(UTC)


@router.post("/mock/events/entry")
def inject_entry(payload: MockEntryRequest, db: Session = Depends(get_db)) -> dict:
    event_id = payload.event_id or _event_id("entry")
    event_time = _timestamp(payload.timestamp)
    full_payload = build_entry_payload(
        event_id=event_id,
        timestamp=event_time,
        symbol=payload.symbol.strip().upper(),
        product=payload.product.strip().upper(),
        quantity=payload.quantity,
        average_price=payload.average_price,
    )
    result = process_payload(db, full_payload)
    return {"data": result, "meta": {"payload": full_payload}}


@router.post("/mock/events/exit")
def inject_exit(payload: MockExitRequest, db: Session = Depends(get_db)) -> dict:
    event_id = payload.event_id or _event_id("exit")
    event_time = _timestamp(payload.timestamp)
    full_payload = build_exit_payload(
        event_id=event_id,
        timestamp=event_time,
        symbol=payload.symbol.strip().upper(),
        product=payload.product.strip().upper(),
        average_price=payload.average_price,
        pnl=payload.pnl,
    )
    result = process_payload(db, full_payload)
    return {"data": result, "meta": {"payload": full_payload}}


@router.post("/mock/events/batch")
def inject_batch(payload: MockBatchRequest, db: Session = Depends(get_db)) -> dict:
    results: list[dict] = []
    for event in payload.events:
        if "event_id" not in event:
            event["event_id"] = _event_id("batch")
        if "timestamp" not in event:
            event["timestamp"] = datetime.now(UTC).isoformat()
        if "event_type" not in event:
            event["event_type"] = "batch"

        try:
            result = process_payload(db, event)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        results.append(result)

    return {"data": results, "meta": {"count": len(results)}}


@router.get("/mock/events/history")
def history(limit: int = 50, db: Session = Depends(get_db)) -> dict:
    safe_limit = max(1, min(limit, 200))
    rows = db.query(MockEvent).order_by(desc(MockEvent.created_at), desc(MockEvent.id)).limit(safe_limit).all()
    data = [
        {
            "id": row.id,
            "event_id": row.event_id,
            "event_type": row.event_type,
            "status": row.status,
            "processed_at": row.processed_at.isoformat() if row.processed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "payload": row.payload,
        }
        for row in rows
    ]
    return {"data": data, "meta": {"count": len(data)}}


@router.post("/mock/events/reset")
def reset_mock_state(keep_tags: bool = False, db: Session = Depends(get_db)) -> dict:
    db.query(NodeCustomTag).delete()
    db.query(Attachment).delete()
    db.query(TradeNode).delete()
    db.query(Trade).delete()
    db.query(PositionState).delete()
    db.query(MockEvent).delete()
    if not keep_tags:
        db.query(CustomTag).delete()
    db.commit()

    if settings.attachments_dir.exists():
        shutil.rmtree(settings.attachments_dir)
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)

    return {"data": {"reset": True, "keep_tags": keep_tags}}
