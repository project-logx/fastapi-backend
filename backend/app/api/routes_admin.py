from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import (
    Attachment,
    BehavioralProfile,
    MockEvent,
    NodeCustomTag,
    NodeEmbedding,
    PositionState,
    RetrospectiveReport,
    Trade,
    TradeNode,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


@router.delete("/admin/clear/reports")
def clear_reports(
    profile_key: Optional[str] = Query(None, description="Only delete reports with this profile key"),
    db: Session = Depends(get_db),
) -> dict:
    """Delete retrospective reports, optionally filtered by profile_key."""
    query = db.query(RetrospectiveReport)
    if profile_key:
        query = query.filter(RetrospectiveReport.profile_key == profile_key.strip())

    count = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    logger.info(f"Cleared {count} retrospective reports (filter: profile_key={profile_key})")
    return {"data": {"deleted_reports": count}}


@router.delete("/admin/clear/trades")
def clear_trades(
    symbol: Optional[str] = Query(None, description="Only delete trades for this symbol"),
    status: Optional[str] = Query(None, description="Only delete trades with this status"),
    db: Session = Depends(get_db),
) -> dict:
    """Delete trades and all related data (nodes, embeddings, attachments)."""
    query = db.query(Trade)
    if symbol:
        query = query.filter(Trade.symbol == symbol.strip().upper())
    if status:
        query = query.filter(Trade.status == status.strip().lower())

    trade_ids = [t.id for t in query.all()]
    if not trade_ids:
        return {"data": {"deleted_trades": 0, "deleted_nodes": 0, "deleted_embeddings": 0}}

    # Delete related records first
    node_count = db.query(TradeNode).filter(TradeNode.trade_id.in_(trade_ids)).count()
    embed_count = db.query(NodeEmbedding).filter(NodeEmbedding.trade_id.in_(trade_ids)).count()

    db.query(NodeCustomTag).filter(
        NodeCustomTag.node_id.in_(
            db.query(TradeNode.id).filter(TradeNode.trade_id.in_(trade_ids))
        )
    ).delete(synchronize_session=False)
    db.query(Attachment).filter(Attachment.trade_id.in_(trade_ids)).delete(synchronize_session=False)
    db.query(NodeEmbedding).filter(NodeEmbedding.trade_id.in_(trade_ids)).delete(synchronize_session=False)
    db.query(TradeNode).filter(TradeNode.trade_id.in_(trade_ids)).delete(synchronize_session=False)
    db.query(Trade).filter(Trade.id.in_(trade_ids)).delete(synchronize_session=False)
    db.commit()

    logger.info(f"Cleared {len(trade_ids)} trades, {node_count} nodes, {embed_count} embeddings (symbol={symbol}, status={status})")
    return {"data": {"deleted_trades": len(trade_ids), "deleted_nodes": node_count, "deleted_embeddings": embed_count}}


@router.delete("/admin/clear/events")
def clear_events(db: Session = Depends(get_db)) -> dict:
    """Delete all mock events and reset position states."""
    event_count = db.query(MockEvent).count()
    position_count = db.query(PositionState).count()

    db.query(MockEvent).delete(synchronize_session=False)
    db.query(PositionState).delete(synchronize_session=False)
    db.commit()

    logger.info(f"Cleared {event_count} mock events, {position_count} position states")
    return {"data": {"deleted_events": event_count, "deleted_positions": position_count}}


@router.delete("/admin/clear/all")
def clear_all(db: Session = Depends(get_db)) -> dict:
    """Nuclear option: delete ALL data (trades, reports, events, profiles). Taxonomy is preserved."""
    counts = {}

    counts["reports"] = db.query(RetrospectiveReport).count()
    db.query(RetrospectiveReport).delete(synchronize_session=False)

    # Attachments, node custom tags, embeddings must go before nodes and trades
    counts["attachments"] = db.query(Attachment).count()
    db.query(Attachment).delete(synchronize_session=False)

    counts["node_custom_tags"] = db.query(NodeCustomTag).count()
    db.query(NodeCustomTag).delete(synchronize_session=False)

    counts["embeddings"] = db.query(NodeEmbedding).count()
    db.query(NodeEmbedding).delete(synchronize_session=False)

    counts["nodes"] = db.query(TradeNode).count()
    db.query(TradeNode).delete(synchronize_session=False)

    counts["trades"] = db.query(Trade).count()
    db.query(Trade).delete(synchronize_session=False)

    counts["events"] = db.query(MockEvent).count()
    db.query(MockEvent).delete(synchronize_session=False)

    counts["positions"] = db.query(PositionState).count()
    db.query(PositionState).delete(synchronize_session=False)

    counts["profiles"] = db.query(BehavioralProfile).count()
    db.query(BehavioralProfile).delete(synchronize_session=False)

    db.commit()

    logger.info(f"CLEARED ALL DATA: {counts}")
    return {"data": {"deleted": counts}}
