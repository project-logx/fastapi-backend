from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, joinedload

from app.constants import normalize_category_name
from app.models import Tag, TagCategory, Trade


def calculate_trade_score(tags: list[Tag]) -> float:
    if not tags:
        return 0.0

    best_contribution_by_category: dict[str, float] = {}
    for tag in tags:
        category = tag.category
        if category is None:
            continue

        available_scores = [row.tag_score for row in category.tags if row.tag_score is not None]
        max_tag_score = max(available_scores) if available_scores else max(1, int(tag.tag_score or 0))
        if max_tag_score <= 0:
            continue

        contribution = (float(tag.tag_score) / float(max_tag_score)) * float(category.category_weight)
        current = best_contribution_by_category.get(category.name)
        if current is None or contribution > current:
            best_contribution_by_category[category.name] = contribution

    return round(sum(best_contribution_by_category.values()), 4)


def _latest_fixed_tags_by_category(trade: Trade) -> dict[str, str]:
    latest: dict[str, str] = {}

    def _sort_key(item) -> tuple[datetime, int]:
        raw = item.captured_at or item.created_at
        if raw is None:
            normalized = datetime.min.replace(tzinfo=UTC)
        elif raw.tzinfo is None:
            normalized = raw.replace(tzinfo=UTC)
        else:
            normalized = raw.astimezone(UTC)
        return normalized, item.id

    ordered_nodes = sorted(trade.nodes, key=_sort_key)
    for node in ordered_nodes:
        payload = node.fixed_tags or {}
        if not isinstance(payload, dict):
            continue
        for raw_category, raw_tag in payload.items():
            category = normalize_category_name(str(raw_category))
            tag_name = str(raw_tag).strip()
            if not category or not tag_name:
                continue
            latest[category] = tag_name
    return latest


def _load_scoring_tags(db: Session, selected: dict[str, str]) -> list[Tag]:
    if not selected:
        return []

    rows = (
        db.query(Tag)
        .options(joinedload(Tag.category).joinedload(TagCategory.tags))
        .join(TagCategory, Tag.category_id == TagCategory.id)
        .filter(TagCategory.name.in_(list(selected.keys())), Tag.name.in_(list(selected.values())))
        .all()
    )

    row_by_pair = {
        (row.category.name, row.name): row
        for row in rows
        if row.category is not None
    }

    missing = [
        f"{category}:{tag_name}"
        for category, tag_name in selected.items()
        if (category, tag_name) not in row_by_pair
    ]
    if missing:
        raise ValueError(f"Unknown taxonomy tags for scoring: {missing}")

    return [row_by_pair[(category, tag_name)] for category, tag_name in selected.items()]


def recompute_trade_quality_score(db: Session, trade: Trade) -> float:
    selected = _latest_fixed_tags_by_category(trade)
    tags = _load_scoring_tags(db, selected)
    score = calculate_trade_score(tags)
    trade.computed_quality_score = score
    return score
