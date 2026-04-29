from __future__ import annotations

from collections.abc import Iterable

from app.constants import SLIDER_DIMENSIONS, TAG_CATEGORIES_BY_NODE_TYPE, TAG_TO_CATEGORY_BY_NODE_TYPE, normalize_category_name
from app.models import Attachment, BehavioralProfile, CustomTag, RetrospectiveReport, Tag, TagCategory, Trade, TradeNode


def serialize_custom_tag(tag: CustomTag) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "category": tag.category,
        "archived_at": tag.archived_at.isoformat() if tag.archived_at else None,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def serialize_tag(tag: Tag) -> dict:
    category_name = tag.category.name if tag.category else None
    return {
        "id": tag.id,
        "name": tag.name,
        "category_id": tag.category_id,
        "category_name": category_name,
        "tag_score": tag.tag_score,
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
    }


def serialize_tag_category(category: TagCategory, include_tags: bool = True) -> dict:
    data = {
        "id": category.id,
        "name": category.name,
        "category_weight": category.category_weight,
        "created_at": category.created_at.isoformat() if category.created_at else None,
    }
    if include_tags:
        ordered_tags = sorted(category.tags, key=lambda item: item.name.lower())
        data["tags"] = [serialize_tag(tag) for tag in ordered_tags]
    return data


def serialize_behavioral_profile(profile: BehavioralProfile) -> dict:
    return {
        "id": profile.id,
        "profile_key": profile.profile_key,
        "user_id": profile.user_id,
        "sweet_spot_centroid": profile.sweet_spot_centroid,
        "danger_zone_centroid": profile.danger_zone_centroid,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def serialize_retrospective_report(report: RetrospectiveReport, include_payload: bool = True) -> dict:
    data = {
        "id": report.id,
        "profile_key": report.profile_key,
        "timeframe_days": report.timeframe_days,
        "period_start": report.period_start.isoformat() if report.period_start else None,
        "period_end": report.period_end.isoformat() if report.period_end else None,
        "trade_count": report.trade_count,
        "synthesis_model": report.synthesis_model,
        "synthesis_source": report.synthesis_source,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }
    if include_payload:
        data["report_markdown"] = report.report_markdown
        data["retrieval_summary"] = report.retrieval_summary or {}
        data["feature_metrics"] = report.feature_metrics or {}
        data["drift_metrics"] = report.drift_metrics or {}
    return data


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
        normalized_raw = {
            normalize_category_name(str(category)): value
            for category, value in raw.items()
        }
        normalized = {
            category: str(normalized_raw[category]).strip()
            for category in categories
            if category in normalized_raw and str(normalized_raw[category]).strip()
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


def _normalize_note(note: str | None) -> str:
    raw = (note or "").strip()
    return " ".join(raw.split())


def _ordered_tag_items(node_type: str, fixed_tags: dict[str, str]) -> Iterable[tuple[str, str]]:
    normalized_tags = {
        normalize_category_name(str(category)): value
        for category, value in fixed_tags.items()
    }
    ordered_categories = TAG_CATEGORIES_BY_NODE_TYPE.get(node_type)
    if ordered_categories:
        for category in ordered_categories:
            value = normalized_tags.get(category)
            if isinstance(value, str) and value.strip():
                yield category, value.strip()
        return

    for category, value in sorted(normalized_tags.items()):
        if isinstance(value, str) and value.strip():
            yield category, value.strip()


def serialize_node_state_for_embedding(
    node_type: str,
    sliders: dict[str, int] | None,
    fixed_tags: dict[str, str] | None,
    note: str | None,
) -> str:
    normalized_node_type = (node_type or "").strip().lower()
    normalized_sliders = sliders or {}
    normalized_fixed_tags = fixed_tags or {}

    tag_payload = "|".join(
        f"{category}:{value}"
        for category, value in _ordered_tag_items(normalized_node_type, normalized_fixed_tags)
    )
    slider_payload = "|".join(
        f"{name}:{int(normalized_sliders[name])}"
        for name in SLIDER_DIMENSIONS
        if name in normalized_sliders and isinstance(normalized_sliders[name], (int, float))
    )

    return " || ".join(
        [
            f"node_type={normalized_node_type}",
            f"fixed_tags={tag_payload or 'none'}",
            f"sliders={slider_payload or 'none'}",
            f"note={_normalize_note(note) or 'none'}",
        ]
    )


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
        "computed_quality_score": trade.computed_quality_score,
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
