from __future__ import annotations

from app.constants import TAG_CATEGORIES_BY_NODE_TYPE, TAG_TO_CATEGORY_BY_NODE_TYPE
from app.models import Attachment, CustomTag, Trade, TradeNode


def serialize_custom_tag(tag: CustomTag) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "category": tag.category,
        "archived_at": tag.archived_at.isoformat() if tag.archived_at else None,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def serialize_attachment(attachment: Attachment, api_prefix: str = "/api/v1") -> dict:
    return {
        "id": attachment.id,
        "file_name": attachment.file_name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "caption": attachment.caption,
        "captured_at": attachment.captured_at.isoformat() if attachment.captured_at else None,
        "url": f"{api_prefix}/attachments/{attachment.id}",
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
    }


def _serialize_fixed_tags_by_type(node: TradeNode) -> dict[str, str]:
    raw = node.fixed_tags or {}
    categories = TAG_CATEGORIES_BY_NODE_TYPE.get(node.node_type, [])
    tag_to_category = TAG_TO_CATEGORY_BY_NODE_TYPE.get(node.node_type, {})

    if isinstance(raw, dict):
        normalized = {
            category: str(raw[category]).strip()
            for category in categories
            if category in raw and str(raw[category]).strip()
        }
        return normalized

    if isinstance(raw, list):
        selected_by_category: dict[str, str] = {}
        for item in raw:
            value = str(item).strip()
            if not value:
                continue
            category = tag_to_category.get(value)
            if category and category not in selected_by_category:
                selected_by_category[category] = value
        return {
            category: selected_by_category[category]
            for category in categories
            if category in selected_by_category
        }

    return {}


def serialize_node(node: TradeNode, api_prefix: str = "/api/v1") -> dict:
    fixed_tags_by_type = _serialize_fixed_tags_by_type(node)
    return {
        "id": node.id,
        "trade_id": node.trade_id,
        "type": node.node_type,
        "captured_at": node.captured_at.isoformat() if node.captured_at else None,
        "fixed_tags": fixed_tags_by_type,
        "fixed_tags_by_type": fixed_tags_by_type,
        "custom_tags": [serialize_custom_tag(tag) for tag in node.custom_tags],
        "sliders": node.sliders or {},
        "note": node.note,
        "is_locked": node.is_locked,
        "attachments": [serialize_attachment(item, api_prefix=api_prefix) for item in node.attachments],
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def serialize_trade(trade: Trade, include_nodes: bool = False, api_prefix: str = "/api/v1") -> dict:
    data = {
        "id": trade.id,
        "symbol": trade.symbol,
        "product": trade.product,
        "direction": trade.direction,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "pnl": trade.pnl,
        "status": trade.status,
        "source_open_event": trade.source_open_event,
        "source_close_event": trade.source_close_event,
        "opened_at": trade.opened_at.isoformat() if trade.opened_at else None,
        "closed_at": trade.closed_at.isoformat() if trade.closed_at else None,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
        "updated_at": trade.updated_at.isoformat() if trade.updated_at else None,
    }
    if include_nodes:
        sorted_nodes = sorted(trade.nodes, key=lambda item: (item.captured_at or item.created_at, item.id))
        data["nodes"] = [serialize_node(node, api_prefix=api_prefix) for node in sorted_nodes]
    return data
