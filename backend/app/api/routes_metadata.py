from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.constants import ALLOWED_TAGS_BY_NODE_TYPE, CATEGORY_WEIGHTS_BY_NAME, FIXED_TAG_OPTIONS_BY_NODE_TYPE, FIXED_TAG_SCORES_BY_CATEGORY, FIXED_TAGS_BY_CATEGORY, MAX_TAG_SCORE_BY_CATEGORY, SLIDER_DIMENSIONS, TAG_CATEGORIES_BY_NODE_TYPE
from app.models import TagCategory


router = APIRouter(tags=["metadata"])


@router.get("/metadata/capture-config")
def capture_config(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(TagCategory)
        .options(joinedload(TagCategory.tags))
        .order_by(TagCategory.id.asc())
        .all()
    )

    if not rows:
        return {
            "data": {
                "sliders": SLIDER_DIMENSIONS,
                "fixed_tags_by_category": FIXED_TAGS_BY_CATEGORY,
                "fixed_tag_scores_by_category": FIXED_TAG_SCORES_BY_CATEGORY,
                "category_weights": CATEGORY_WEIGHTS_BY_NAME,
                "max_tag_score_by_category": MAX_TAG_SCORE_BY_CATEGORY,
                "tag_categories_by_node_type": TAG_CATEGORIES_BY_NODE_TYPE,
                "fixed_tag_options_by_node_type": FIXED_TAG_OPTIONS_BY_NODE_TYPE,
                "allowed_tags": ALLOWED_TAGS_BY_NODE_TYPE,
            }
        }

    fixed_tags_by_category: dict[str, list[str]] = {}
    fixed_tag_scores_by_category: dict[str, dict[str, int]] = {}
    category_weights: dict[str, int] = {}
    max_tag_score_by_category: dict[str, int] = {}

    for category in rows:
        ordered_tags = sorted(category.tags, key=lambda item: item.id)
        names = [row.name for row in ordered_tags]
        scores = {row.name: int(row.tag_score) for row in ordered_tags}

        fixed_tags_by_category[category.name] = names
        fixed_tag_scores_by_category[category.name] = scores
        category_weights[category.name] = int(category.category_weight)
        max_tag_score_by_category[category.name] = max(scores.values()) if scores else 0

    fixed_tag_options_by_node_type = {
        node_type: {
            category: list(fixed_tags_by_category.get(category, []))
            for category in categories
        }
        for node_type, categories in TAG_CATEGORIES_BY_NODE_TYPE.items()
    }

    allowed_tags_by_node_type = {
        node_type: [
            tag
            for category in categories
            for tag in fixed_tags_by_category.get(category, [])
        ]
        for node_type, categories in TAG_CATEGORIES_BY_NODE_TYPE.items()
    }

    return {
        "data": {
            "sliders": SLIDER_DIMENSIONS,
            "fixed_tags_by_category": fixed_tags_by_category,
            "fixed_tag_scores_by_category": fixed_tag_scores_by_category,
            "category_weights": category_weights,
            "max_tag_score_by_category": max_tag_score_by_category,
            "tag_categories_by_node_type": TAG_CATEGORIES_BY_NODE_TYPE,
            "fixed_tag_options_by_node_type": fixed_tag_options_by_node_type,
            "allowed_tags": allowed_tags_by_node_type,
        }
    }
