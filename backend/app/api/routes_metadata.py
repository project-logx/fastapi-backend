from __future__ import annotations

from fastapi import APIRouter

from app.constants import ALLOWED_TAGS_BY_NODE_TYPE, FIXED_TAG_OPTIONS_BY_NODE_TYPE, FIXED_TAGS_BY_CATEGORY, SLIDER_DIMENSIONS, TAG_CATEGORIES_BY_NODE_TYPE


router = APIRouter(tags=["metadata"])


@router.get("/metadata/capture-config")
def capture_config() -> dict:
    return {
        "data": {
            "sliders": SLIDER_DIMENSIONS,
            "fixed_tags_by_category": FIXED_TAGS_BY_CATEGORY,
            "tag_categories_by_node_type": TAG_CATEGORIES_BY_NODE_TYPE,
            "fixed_tag_options_by_node_type": FIXED_TAG_OPTIONS_BY_NODE_TYPE,
            "allowed_tags": ALLOWED_TAGS_BY_NODE_TYPE,
        }
    }
