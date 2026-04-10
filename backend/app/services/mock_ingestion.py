from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models import MockEvent, PositionState, Trade, TradeStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(raw: str | datetime | None) -> datetime:
    if raw is None:
        return utc_now()
    if isinstance(raw, datetime):
        parsed = raw
    else:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_entry_payload(event_id: str, timestamp: datetime, symbol: str, product: str, quantity: int, average_price: float) -> dict:
    order_id = f"ord-{event_id}"
    trade_id = f"trd-{event_id}"
    ts = timestamp.isoformat()
    return {
        "event_id": event_id,
        "event_type": "entry",
        "timestamp": ts,
        "orders": [
            {
                "order_id": order_id,
                "status": "COMPLETE",
                "tradingsymbol": symbol,
                "transaction_type": "BUY" if quantity > 0 else "SELL",
                "product": product,
                "quantity": abs(quantity),
                "average_price": average_price,
                "exchange_timestamp": ts,
            }
        ],
        "trades": [
            {
                "trade_id": trade_id,
                "order_id": order_id,
                "tradingsymbol": symbol,
                "transaction_type": "BUY" if quantity > 0 else "SELL",
                "quantity": abs(quantity),
                "average_price": average_price,
                "fill_timestamp": ts,
            }
        ],
        "positions": [
            {
                "tradingsymbol": symbol,
                "product": product,
                "net_quantity": quantity,
                "average_price": average_price,
                "pnl": 0.0,
            }
        ],
    }


def build_exit_payload(event_id: str, timestamp: datetime, symbol: str, product: str, average_price: float, pnl: float) -> dict:
    order_id = f"ord-{event_id}"
    trade_id = f"trd-{event_id}"
    ts = timestamp.isoformat()
    return {
        "event_id": event_id,
        "event_type": "exit",
        "timestamp": ts,
        "orders": [
            {
                "order_id": order_id,
                "status": "COMPLETE",
                "tradingsymbol": symbol,
                "transaction_type": "SELL",
                "product": product,
                "quantity": 0,
                "average_price": average_price,
                "exchange_timestamp": ts,
            }
        ],
        "trades": [
            {
                "trade_id": trade_id,
                "order_id": order_id,
                "tradingsymbol": symbol,
                "transaction_type": "SELL",
                "quantity": 0,
                "average_price": average_price,
                "fill_timestamp": ts,
            }
        ],
        "positions": [
            {
                "tradingsymbol": symbol,
                "product": product,
                "net_quantity": 0,
                "average_price": average_price,
                "pnl": pnl,
            }
        ],
    }


def _latest_open_trade(db: Session, symbol: str, product: str) -> Trade | None:
    open_states = [TradeStatus.PENDING_ENTRY.value, TradeStatus.ACTIVE.value, TradeStatus.PENDING_EXIT.value]
    return (
        db.query(Trade)
        .filter(Trade.symbol == symbol, Trade.product == product, Trade.status.in_(open_states))
        .order_by(desc(Trade.opened_at), desc(Trade.id))
        .first()
    )


def process_payload(db: Session, payload: dict) -> dict:
    event_id = payload.get("event_id")
    if not event_id:
        raise ValueError("payload missing event_id")

    existing = db.query(MockEvent).filter(MockEvent.event_id == event_id).first()
    if existing:
        return {
            "event_id": event_id,
            "status": "duplicate",
            "transitions": [],
        }

    event_type = payload.get("event_type", "unknown")
    event_time = parse_timestamp(payload.get("timestamp"))
    transitions: list[dict] = []

    event = MockEvent(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        status="processed",
        processed_at=utc_now(),
    )
    db.add(event)

    for item in payload.get("positions", []):
        symbol = str(item.get("tradingsymbol", "")).strip().upper()
        product = str(item.get("product", "MIS")).strip().upper()
        if not symbol:
            continue

        net_quantity = int(item.get("net_quantity", 0) or 0)
        average_price = float(item.get("average_price", 0.0) or 0.0)
        pnl = float(item.get("pnl", 0.0) or 0.0)

        position = (
            db.query(PositionState)
            .filter(PositionState.symbol == symbol, PositionState.product == product)
            .first()
        )

        previous_qty = position.net_quantity if position else 0

        if position is None:
            position = PositionState(
                symbol=symbol,
                product=product,
                net_quantity=net_quantity,
                average_price=average_price,
                pnl=pnl,
                updated_at=event_time,
            )
            db.add(position)
        else:
            position.net_quantity = net_quantity
            position.average_price = average_price
            position.pnl = pnl
            position.updated_at = event_time

        flipped = (previous_qty > 0 and net_quantity < 0) or (previous_qty < 0 and net_quantity > 0)

        if previous_qty == 0 and net_quantity != 0:
            new_trade = Trade(
                symbol=symbol,
                product=product,
                direction="LONG" if net_quantity > 0 else "SHORT",
                quantity=abs(net_quantity),
                entry_price=average_price,
                status=TradeStatus.PENDING_ENTRY.value,
                source_open_event=event_id,
                opened_at=event_time,
            )
            db.add(new_trade)
            db.flush()
            transitions.append(
                {
                    "action": "opened",
                    "trade_id": new_trade.id,
                    "from": 0,
                    "to": net_quantity,
                    "symbol": symbol,
                    "product": product,
                }
            )
            continue

        if previous_qty != 0 and net_quantity == 0:
            open_trade = _latest_open_trade(db, symbol, product)
            if open_trade:
                open_trade.status = TradeStatus.PENDING_EXIT.value
                open_trade.exit_price = average_price if average_price > 0 else open_trade.exit_price
                open_trade.pnl = pnl
                open_trade.closed_at = event_time
                open_trade.source_close_event = event_id
                transitions.append(
                    {
                        "action": "pending_exit",
                        "trade_id": open_trade.id,
                        "from": previous_qty,
                        "to": 0,
                        "symbol": symbol,
                        "product": product,
                    }
                )
            continue

        if flipped:
            open_trade = _latest_open_trade(db, symbol, product)
            if open_trade:
                open_trade.status = TradeStatus.PENDING_EXIT.value
                open_trade.exit_price = average_price if average_price > 0 else open_trade.exit_price
                open_trade.pnl = pnl
                open_trade.closed_at = event_time
                open_trade.source_close_event = event_id
                transitions.append(
                    {
                        "action": "flip_pending_exit",
                        "trade_id": open_trade.id,
                        "from": previous_qty,
                        "to": 0,
                        "symbol": symbol,
                        "product": product,
                    }
                )

            new_trade = Trade(
                symbol=symbol,
                product=product,
                direction="LONG" if net_quantity > 0 else "SHORT",
                quantity=abs(net_quantity),
                entry_price=average_price,
                status=TradeStatus.PENDING_ENTRY.value,
                source_open_event=event_id,
                opened_at=event_time,
            )
            db.add(new_trade)
            db.flush()
            transitions.append(
                {
                    "action": "flip_opened",
                    "trade_id": new_trade.id,
                    "from": 0,
                    "to": net_quantity,
                    "symbol": symbol,
                    "product": product,
                }
            )

    db.commit()

    return {
        "event_id": event_id,
        "status": "processed",
        "transitions": transitions,
    }
