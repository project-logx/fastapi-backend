from __future__ import annotations

SLIDER_DIMENSIONS = [
    "Confidence",
    "Stress",
    "Focus",
    "Market Clarity",
    "Patience",
]

FIXED_TAXONOMY: dict[str, dict] = {
    "Direction": {
        "category_weight": 5,
        "node_types": ["entry", "mid"],
        "tags": {
            "Long": 10,
            "Short": 10,
        },
    },
    "Strategy": {
        "category_weight": 25,
        "node_types": ["entry", "mid"],
        "tags": {
            "Breakout": 8,
            "Pullback": 7,
            "Price action": 7,
            "Reversal": 6,
        },
    },
    "Market": {
        "category_weight": 15,
        "node_types": ["entry", "mid"],
        "tags": {
            "trending day": 9,
            "Range day": 7,
            "High volatility": 6,
            "Expiry day": 6,
            "News driven": 5,
        },
    },
    "Execution": {
        "category_weight": 30,
        "node_types": ["exit"],
        "tags": {
            "good R:R": 8,
            "Poor R:R": 4,
            "Oversized": 3,
            "Perfect entry": 10,
            "Early entry": 6,
            "Late entry": 5,
            "Premature exit": 4,
            "Perfect exit": 10,
            "Late exit": 6,
        },
    },
    "Quality": {
        "category_weight": 20,
        "node_types": ["exit"],
        "tags": {
            "a+": 10,
            "Rule break": 5,
            "Slippage": 6,
            "Followed plan": 9,
            "No plan": 2,
            "Overtraded": 3,
            "Random trade": 1,
            "Impulsive": 2,
        },
    },
    "Outcome": {
        "category_weight": 5,
        "node_types": ["exit"],
        "tags": {
            "Target hit": 10,
            "Stop hit": 4,
            "Partial exit": 7,
            "Time exit": 6,
            "Manual close": 5,
        },
    },
}

CATEGORY_NAME_ALIASES = {
    "Market context": "Market",
    "Result quality": "Quality",
}


def _build_category_lookup() -> dict[str, str]:
    lookup = {name.lower(): name for name in FIXED_TAXONOMY.keys()}
    for alias, canonical in CATEGORY_NAME_ALIASES.items():
        lookup[alias.lower()] = canonical
    return lookup


CANONICAL_CATEGORY_BY_LOWER = _build_category_lookup()


def normalize_category_name(raw_name: str) -> str:
    cleaned = " ".join((raw_name or "").split()).strip()
    if not cleaned:
        return cleaned
    return CANONICAL_CATEGORY_BY_LOWER.get(cleaned.lower(), cleaned)


CATEGORY_WEIGHTS_BY_NAME = {
    category: int(definition["category_weight"])
    for category, definition in FIXED_TAXONOMY.items()
}

FIXED_TAGS_BY_CATEGORY = {
    category: list(definition["tags"].keys())
    for category, definition in FIXED_TAXONOMY.items()
}

FIXED_TAG_SCORES_BY_CATEGORY = {
    category: {
        tag: int(score)
        for tag, score in definition["tags"].items()
    }
    for category, definition in FIXED_TAXONOMY.items()
}

MAX_TAG_SCORE_BY_CATEGORY = {
    category: max(tag_scores.values()) if tag_scores else 0
    for category, tag_scores in FIXED_TAG_SCORES_BY_CATEGORY.items()
}

TAG_CATEGORIES_BY_NODE_TYPE: dict[str, list[str]] = {"entry": [], "mid": [], "exit": []}
for category, definition in FIXED_TAXONOMY.items():
    for node_type in definition["node_types"]:
        TAG_CATEGORIES_BY_NODE_TYPE[node_type].append(category)

FIXED_TAG_OPTIONS_BY_NODE_TYPE = {
    node_type: {
        category: FIXED_TAGS_BY_CATEGORY[category]
        for category in categories
    }
    for node_type, categories in TAG_CATEGORIES_BY_NODE_TYPE.items()
}


def _flatten_allowed_tags(categories: list[str]) -> list[str]:
    tags: list[str] = []
    for category in categories:
        tags.extend(FIXED_TAGS_BY_CATEGORY[category])
    return tags


ALLOWED_TAGS_BY_NODE_TYPE = {
    node_type: _flatten_allowed_tags(categories)
    for node_type, categories in TAG_CATEGORIES_BY_NODE_TYPE.items()
}

TAG_TO_CATEGORY_BY_NODE_TYPE = {
    node_type: {
        tag: category
        for category in categories
        for tag in FIXED_TAGS_BY_CATEGORY[category]
    }
    for node_type, categories in TAG_CATEGORIES_BY_NODE_TYPE.items()
}

NODE_TYPES = tuple(TAG_CATEGORIES_BY_NODE_TYPE.keys())

ALLOWED_IMAGE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_NODE = 10
