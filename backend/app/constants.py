from __future__ import annotations

SLIDER_DIMENSIONS = [
    "Confidence",
    "Stress",
    "Focus",
    "Market Clarity",
    "Patience",
]

FIXED_TAGS_BY_CATEGORY = {
    "Direction": ["Long", "Short"],
    "Strategy": ["Breakout", "Pullback", "Price action", "Reversal"],
    "Market context": ["trending day", "Range day", "High volatility", "Expiry day", "News driven"],
    "Execution": [
        "good R:R",
        "Poor R:R",
        "Oversized",
        "Perfect entry",
        "Early entry",
        "Late entry",
        "Premature exit",
        "Perfect exit",
        "Late exit",
    ],
    "Result quality": ["a+", "Rule break", "Slippage", "Followed plan", "No plan", "Overtraded", "Random trade", "Impulsive"],
    "Outcome": ["Target hit", "Stop hit", "Partial exit", "Time exit", "Manual close"],
}

TAG_CATEGORIES_BY_NODE_TYPE = {
    "entry": ["Direction", "Strategy", "Market context"],
    "mid": ["Direction", "Strategy", "Market context"],
    "exit": ["Execution", "Result quality", "Outcome"],
}

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
