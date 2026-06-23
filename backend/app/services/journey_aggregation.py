from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.models import Trade, TradeNode, TradeStatus


_FALLBACK_TIME = datetime.min.replace(tzinfo=UTC)  


def _node_sort_key(node: TradeNode) -> tuple[datetime, int]:
    anchor = node.captured_at or node.created_at or _FALLBACK_TIME
    return anchor, node.id


def _trading_day_bounds(reference_dt: datetime) -> tuple[datetime, datetime]:
    """
    Return (start, end) of the trading day containing `reference_dt`.
    Uses the calendar date in UTC to define the day window.
    """
    if reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=UTC)
    ref_utc = reference_dt.astimezone(UTC)
    day_start = datetime.combine(ref_utc.date(), time.min, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


def related_trades_for_journey(db: Session, trade: Trade) -> list[Trade]:
    """
    Find all trades related to a journey by matching symbol + product
    within the same trading day as the primary trade.
    """
    # Determine the trading day from the primary trade's opened_at
    ref_time = trade.opened_at or trade.created_at or datetime.now(UTC)
    day_start, day_end = _trading_day_bounds(ref_time)

    query = (
        db.query(Trade)
        .options(joinedload(Trade.nodes))
        .filter(
            Trade.symbol == trade.symbol,
            Trade.product == trade.product,
            Trade.opened_at >= day_start,
            Trade.opened_at < day_end,
        )
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
    """Merge entry/mid/exit nodes across BUY and SELL legs sharing the same symbol+product on the same day."""
    entry_node = _collect_nodes(trades, "entry", prefer_direction="BUY", latest=False)
    mid_node = _collect_nodes(trades, "mid", prefer_direction="BUY", latest=True)
    exit_node = _collect_nodes(trades, "exit", prefer_direction="SELL", latest=True)

    ordered: list[TradeNode] = []
    for node in (entry_node, mid_node, exit_node):
        if node is not None:
            ordered.append(node)
    return ordered


def list_primary_journey_trades(db: Session, *, symbol: str | None = None, limit: int = 100, current_user) -> list[Trade]:
    """Return one representative completed trade per symbol+product+day journey."""
    safe_limit = max(1, min(limit, 500))
    query = (
        db.query(Trade)
        .options(joinedload(Trade.nodes))
        .filter(Trade.status == TradeStatus.COMPLETE.value, Trade.user_id == current_user.id)
    )
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())

    rows = query.order_by(Trade.closed_at.desc(), Trade.id.desc()).all()

    # Dedup by (symbol, product, trading_day) so each day's journey is one entry
    seen_keys: set[tuple[str, str, str]] = set()
    primary_trades: list[Trade] = []
    for trade in rows:
        ref_time = trade.opened_at or trade.created_at or datetime.now(UTC)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=UTC)
        day_key = ref_time.astimezone(UTC).date().isoformat()
        key = (trade.symbol, trade.product, day_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        primary_trades.append(trade)
        if len(primary_trades) >= safe_limit:
            break

    return primary_trades
