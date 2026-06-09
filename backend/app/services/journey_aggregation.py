from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, joinedload

from app.models import Trade, TradeNode, TradeStatus


_FALLBACK_TIME = datetime.min.replace(tzinfo=UTC)  


def _node_sort_key(node: TradeNode) -> tuple[datetime, int]:
    anchor = node.captured_at or node.created_at or _FALLBACK_TIME
    return anchor, node.id


def related_trades_for_journey(db: Session, trade: Trade) -> list[Trade]:
    query = (
        db.query(Trade)
        .options(joinedload(Trade.nodes))
        .filter(Trade.instrument_token == trade.instrument_token)
    )
    if trade.user_id is not None:
        query = query.filter(Trade.user_id == trade.user_id)
    return query.order_by(Trade.opened_at.asc(), Trade.id.asc()).all()


def _collect_nodes(
    trades: list[Trade],
    node_type: str,
    *,
    prefer_direction: str | None = None,
    latest: bool = False,
) -> TradeNode | None:
    preferred_trades = [
        trade for trade in trades if prefer_direction and str(trade.direction).upper() == prefer_direction.upper()
    ]
    search_trades = preferred_trades or trades

    candidates: list[TradeNode] = []
    for trade in search_trades:
        for node in trade.nodes:
            if node.node_type == node_type:
                candidates.append(node)

    if not candidates and prefer_direction:
        for trade in trades:
            for node in trade.nodes:
                if node.node_type == node_type:
                    candidates.append(node)

    if not candidates:
        return None

    if latest:
        return max(candidates, key=_node_sort_key)
    return min(candidates, key=_node_sort_key)


def collect_journey_nodes(trades: list[Trade]) -> list[TradeNode]:
    """Merge entry/mid/exit nodes across BUY and SELL legs sharing an instrument_token."""
    entry_node = _collect_nodes(trades, "entry", prefer_direction="BUY", latest=False)
    mid_node = _collect_nodes(trades, "mid", prefer_direction="BUY", latest=True)
    exit_node = _collect_nodes(trades, "exit", prefer_direction="SELL", latest=True)

    ordered: list[TradeNode] = []
    for node in (entry_node, mid_node, exit_node):
        if node is not None:
            ordered.append(node)
    return ordered


def list_primary_journey_trades(db: Session, *, symbol: str | None = None, limit: int = 100) -> list[Trade]:
    """Return one representative completed trade per instrument_token journey."""
    safe_limit = max(1, min(limit, 500))
    query = (
        db.query(Trade)
        .options(joinedload(Trade.nodes))
        .filter(Trade.status == TradeStatus.COMPLETE.value)
    )
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())

    rows = query.order_by(Trade.closed_at.desc(), Trade.id.desc()).all()

    seen_tokens: set[int] = set()
    primary_trades: list[Trade] = []
    for trade in rows:
        if trade.instrument_token in seen_tokens:
            continue
        seen_tokens.add(trade.instrument_token)
        primary_trades.append(trade)
        if len(primary_trades) >= safe_limit:
            break

    return primary_trades
