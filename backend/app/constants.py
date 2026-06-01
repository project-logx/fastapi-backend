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

VERIFICATION_EMAIL_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Verify your email</title>
</head>
<body style="margin:0;padding:0;background-color:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#0b0f19;">
    <span style="display:none;opacity:0;color:transparent;height:0;width:0;overflow:hidden;">
        Confirm your email to finish setting up your LogX account.
    </span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background-color:#f6f7fb;">
        <tr>
            <td align="center" style="padding:32px 16px;">
                <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="border-collapse:collapse;max-width:600px;width:100%;background-color:#ffffff;border-radius:16px;box-shadow:0 8px 24px rgba(15,23,42,0.08);">
                    <tr>
                        <td style="padding:32px 32px 16px 32px;border-bottom:1px solid #eef2f7;">
                            <div style="font-size:18px;font-weight:700;letter-spacing:0.2px;">
                                LogX
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:32px;">
                            <h1 style="margin:0 0 12px 0;font-size:24px;line-height:1.3;">Verify your email</h1>
                            <p style="margin:0 0 20px 0;font-size:15px;line-height:1.6;color:#374151;">
                                Thanks for signing up. Please confirm your email address to activate your LogX account.
                            </p>
                            <div style="margin:24px 0;">
                                <a href="{link}" style="display:inline-block;background-color:#0b0f19;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;">
                                    Verify email
                                </a>
                            </div>
                            <p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#6b7280;">
                                This link will expire in 30 minutes. If you did not create a LogX account, you can safely ignore this email.
                            </p>
                            <p style="margin:16px 0 0 0;font-size:12px;line-height:1.6;color:#9ca3af;word-break:break-all;">
                                If the button does not work, copy and paste this URL into your browser:<br />
                                <a href="{link}" style="color:#0b0f19;text-decoration:underline;">{link}</a>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:20px 32px;border-top:1px solid #eef2f7;font-size:12px;color:#9ca3af;">
                            LogX Team · support@logxapp.in
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

PASSWORD_CHANGE_SUCCESS_EMAIL_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Password changed</title>
</head>
<body style="margin:0;padding:0;background-color:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#0b0f19;">
    <span style="display:none;opacity:0;color:transparent;height:0;width:0;overflow:hidden;">
        Your LogX password was updated successfully.
    </span>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;background-color:#f6f7fb;">
        <tr>
            <td align="center" style="padding:32px 16px;">
                <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="border-collapse:collapse;max-width:600px;width:100%;background-color:#ffffff;border-radius:16px;box-shadow:0 8px 24px rgba(15,23,42,0.08);">
                    <tr>
                        <td style="padding:32px 32px 16px 32px;border-bottom:1px solid #eef2f7;">
                            <div style="font-size:18px;font-weight:700;letter-spacing:0.2px;">
                                LogX
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:32px;">
                            <h1 style="margin:0 0 12px 0;font-size:24px;line-height:1.3;">Password changed</h1>
                            <p style="margin:0 0 12px 0;font-size:15px;line-height:1.6;color:#374151;">
                                The password for <strong>{email}</strong> was updated successfully.
                            </p>
                            <p style="margin:0 0 12px 0;font-size:14px;line-height:1.6;color:#6b7280;">
                                If you did not make this change, reset your password immediately or contact support.
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:20px 32px;border-top:1px solid #eef2f7;font-size:12px;color:#9ca3af;">
                            LogX Team · support@logxapp.in
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


PASSWORD_RESET_EMAIL_HTML_TEMPLATE = """"
<!doctype html>
<html lang=\"en\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Reset your password</title>
</head>
<body style=\"margin:0;padding:0;background-color:#f6f7fb;font-family:Arial,Helvetica,sans-serif;color:#0b0f19;\">
    <span style=\"display:none;opacity:0;color:transparent;height:0;width:0;overflow:hidden;\">
        Reset your LogX password using the link below.
    </span>
    <table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;background-color:#f6f7fb;\">
        <tr>
            <td align=\"center\" style=\"padding:32px 16px;\">
                <table role=\"presentation\" width=\"600\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;max-width:600px;width:100%;background-color:#ffffff;border-radius:16px;box-shadow:0 8px 24px rgba(15,23,42,0.08);\">
                    <tr>
                        <td style=\"padding:32px 32px 16px 32px;border-bottom:1px solid #eef2f7;\">
                            <div style=\"font-size:18px;font-weight:700;letter-spacing:0.2px;\">
                                LogX
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td style=\"padding:32px;\">
                            <h1 style=\"margin:0 0 12px 0;font-size:24px;line-height:1.3;\">Reset your password</h1>
                            <p style=\"margin:0 0 20px 0;font-size:15px;line-height:1.6;color:#374151;\">
                                We received a request to reset your LogX password. Use the button below to set a new password.
                            </p>
                            <div style=\"margin:24px 0;\">
                                <a href=\"{link}\" style=\"display:inline-block;background-color:#0b0f19;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:10px;font-size:14px;font-weight:600;\">
                                    Reset password
                                </a>
                            </div>
                            <p style=\"margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#6b7280;\">
                                This link will expire in 1 hour. If you did not request a password reset, you can safely ignore this email.
                            </p>
                            <p style=\"margin:16px 0 0 0;font-size:12px;line-height:1.6;color:#9ca3af;word-break:break-all;\">
                                If the button does not work, copy and paste this URL into your browser:<br />
                                <a href=\"{link}\" style=\"color:#0b0f19;text-decoration:underline;\">{link}</a>
                            </p>
                        </td>
                    </tr>
                    <tr>
                        <td style=\"padding:20px 32px;border-top:1px solid #eef2f7;font-size:12px;color:#9ca3af;\">
                            LogX Team · support@logxapp.in
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""