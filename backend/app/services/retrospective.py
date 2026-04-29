from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.constants import SLIDER_DIMENSIONS, normalize_category_name
from app.models import NodeEmbedding, RetrospectiveReport, Trade, TradeNode, TradeStatus
from app.services.embeddings import get_or_create_behavioral_profile
from app.services.intervention import cosine_similarity
from app.services.serialization import serialize_node_state_for_embedding, serialize_retrospective_report


try:
    from langchain_core.documents import Document as LangChainDocument
except Exception:

    @dataclass
    class LangChainDocument:  # type: ignore[no-redef]
        page_content: str
        metadata: dict[str, Any]


def _to_utc_datetime(raw: datetime | None) -> datetime:
    if raw is None:
        return datetime.now(UTC)
    if raw.tzinfo is None:
        return raw.replace(tzinfo=UTC)
    return raw.astimezone(UTC)


def _vector_norm(vector: list[float]) -> float:
    return math.sqrt(sum(item * item for item in vector)) if vector else 0.0


def _normalize_sliders(raw: dict | None) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, value in raw.items():
        try:
            normalized[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _normalize_fixed_tags(raw: dict | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, str] = {}
    for category, tag in raw.items():
        category_name = normalize_category_name(str(category))
        tag_name = str(tag).strip()
        if not category_name or not tag_name:
            continue
        normalized[category_name] = tag_name
    return normalized


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(mean(values))


def _pearson(values: list[float], targets: list[float]) -> float:
    if len(values) != len(targets) or len(values) < 2:
        return 0.0

    mean_x = _safe_mean(values)
    mean_y = _safe_mean(targets)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(values, targets))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in values))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in targets))

    if denom_x == 0.0 or denom_y == 0.0:
        return 0.0
    return numerator / (denom_x * denom_y)


def _compute_slider_delta(entry_sliders: dict[str, int], exit_sliders: dict[str, int]) -> dict[str, float]:
    delta: dict[str, float] = {}
    for slider_name in SLIDER_DIMENSIONS:
        if slider_name not in entry_sliders or slider_name not in exit_sliders:
            continue
        delta[slider_name] = round(float(exit_sliders[slider_name]) - float(entry_sliders[slider_name]), 4)
    return delta


def _first_node_of_type(nodes: list[TradeNode], node_type: str) -> TradeNode | None:
    matches = [node for node in nodes if node.node_type == node_type]
    if not matches:
        return None
    ordered = sorted(matches, key=lambda row: (_to_utc_datetime(row.captured_at), row.id))
    return ordered[0]


def _last_node_of_type(nodes: list[TradeNode], node_type: str) -> TradeNode | None:
    matches = [node for node in nodes if node.node_type == node_type]
    if not matches:
        return None
    ordered = sorted(matches, key=lambda row: (_to_utc_datetime(row.captured_at), row.id))
    return ordered[-1]


def _node_label(node_type: str, mid_index: int) -> str:
    if node_type == "entry":
        return "Start"
    if node_type == "mid":
        return f"Mid {mid_index}"
    if node_type == "exit":
        return "End"
    return node_type.title() or "Node"


def _trade_delta_record(trade: Trade) -> dict[str, Any] | None:
    nodes = sorted(trade.nodes, key=lambda row: (_to_utc_datetime(row.captured_at), row.id))
    if not nodes:
        return None

    entry_node = _first_node_of_type(nodes, "entry")
    exit_node = _last_node_of_type(nodes, "exit")
    if entry_node is None or exit_node is None:
        return None

    entry_fixed_tags = _normalize_fixed_tags(entry_node.fixed_tags)
    exit_fixed_tags = _normalize_fixed_tags(exit_node.fixed_tags)
    entry_sliders = _normalize_sliders(entry_node.sliders)
    exit_sliders = _normalize_sliders(exit_node.sliders)

    entry_custom = sorted({tag.name for tag in entry_node.custom_tags if tag.name})
    exit_custom = sorted({tag.name for tag in exit_node.custom_tags if tag.name})

    slider_delta = _compute_slider_delta(entry_sliders, exit_sliders)

    mid_count = sum(1 for node in nodes if node.node_type == "mid")
    timeline: list[str] = []
    mid_index = 0
    for node in nodes:
        node_type = str(node.node_type or "")
        if node_type == "mid":
            mid_index += 1
        timestamp = _to_utc_datetime(node.captured_at).isoformat()
        timeline.append(f"{_node_label(node_type, mid_index)} ({timestamp})")

    entry_note = (entry_node.note or "").strip()
    exit_note = (exit_node.note or "").strip()

    entry_serialized = serialize_node_state_for_embedding(
        node_type="entry",
        sliders=entry_sliders,
        fixed_tags=entry_fixed_tags,
        note=entry_note,
    )
    exit_serialized = serialize_node_state_for_embedding(
        node_type="exit",
        sliders=exit_sliders,
        fixed_tags=exit_fixed_tags,
        note=exit_note,
    )

    return {
        "trade_id": trade.id,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "pnl": float(trade.pnl or 0.0),
        "quality_score": float(trade.computed_quality_score or 0.0),
        "opened_at": _to_utc_datetime(trade.opened_at).isoformat() if trade.opened_at else None,
        "closed_at": _to_utc_datetime(trade.closed_at).isoformat() if trade.closed_at else None,
        "timeline": timeline,
        "mid_node_count": mid_count,
        "entry": {
            "node_id": entry_node.id,
            "captured_at": _to_utc_datetime(entry_node.captured_at).isoformat(),
            "fixed_tags": entry_fixed_tags,
            "sliders": entry_sliders,
            "note": entry_note,
            "custom_tags": entry_custom,
            "serialized_state": entry_serialized,
        },
        "exit": {
            "node_id": exit_node.id,
            "captured_at": _to_utc_datetime(exit_node.captured_at).isoformat(),
            "fixed_tags": exit_fixed_tags,
            "sliders": exit_sliders,
            "note": exit_note,
            "custom_tags": exit_custom,
            "serialized_state": exit_serialized,
        },
        "delta": {
            "slider_delta": slider_delta,
            "entry_only_custom_tags": sorted(set(entry_custom) - set(exit_custom)),
            "exit_only_custom_tags": sorted(set(exit_custom) - set(entry_custom)),
            "note_length_delta": len(exit_note) - len(entry_note),
        },
    }


class TimeframeTradeRetriever:
    """LangChain-style retriever that converts timeframe trade histories into documents."""

    def __init__(
        self,
        db: Session,
        timeframe_days: int,
        profile_key: str,
        max_trades: int,
    ) -> None:
        self.db = db
        self.timeframe_days = max(1, min(int(timeframe_days), 90))
        self.profile_key = (profile_key or "global").strip() or "global"
        self.max_trades = max(1, min(int(max_trades), 1000))
        self.period_end = datetime.now(UTC)
        self.period_start = self.period_end - timedelta(days=self.timeframe_days)

        self._trade_rows: list[Trade] | None = None
        self._trade_histories: list[dict[str, Any]] | None = None

    @property
    def trade_rows(self) -> list[Trade]:
        if self._trade_rows is None:
            rows = (
                self.db.query(Trade)
                .options(
                    joinedload(Trade.nodes).joinedload(TradeNode.custom_tags),
                    joinedload(Trade.embeddings),
                )
                .filter(
                    Trade.status == TradeStatus.COMPLETE.value,
                    Trade.closed_at.isnot(None),
                    Trade.closed_at >= self.period_start,
                )
                .order_by(desc(Trade.closed_at), desc(Trade.id))
                .limit(self.max_trades)
                .all()
            )
            self._trade_rows = rows
        return self._trade_rows

    @property
    def trade_histories(self) -> list[dict[str, Any]]:
        if self._trade_histories is None:
            rows: list[dict[str, Any]] = []
            for trade in self.trade_rows:
                record = _trade_delta_record(trade)
                if record is not None:
                    rows.append(record)
            self._trade_histories = rows
        return self._trade_histories

    def get_relevant_documents(self, query: str = "") -> list[LangChainDocument]:
        documents: list[LangChainDocument] = []
        for history in self.trade_histories:
            documents.append(
                LangChainDocument(
                    page_content=json.dumps(history, ensure_ascii=True),
                    metadata={
                        "trade_id": history["trade_id"],
                        "symbol": history["symbol"],
                        "query": query,
                        "timeframe_days": self.timeframe_days,
                    },
                )
            )
        return documents


def _average_slider_delta(histories: list[dict[str, Any]]) -> dict[str, float]:
    values_by_slider: dict[str, list[float]] = defaultdict(list)
    for history in histories:
        slider_delta = history.get("delta", {}).get("slider_delta", {})
        if not isinstance(slider_delta, dict):
            continue
        for slider_name, raw_value in slider_delta.items():
            try:
                values_by_slider[str(slider_name)].append(float(raw_value))
            except (TypeError, ValueError):
                continue

    return {
        slider_name: round(_safe_mean(values), 4)
        for slider_name, values in sorted(values_by_slider.items())
    }


def _feature_rows(histories: list[dict[str, Any]]) -> tuple[list[dict[str, float]], list[float]]:
    feature_rows: list[dict[str, float]] = []
    pnl_values: list[float] = []

    for history in histories:
        entry = history.get("entry", {})
        delta = history.get("delta", {})

        row: dict[str, float] = {}

        sliders = entry.get("sliders", {}) if isinstance(entry, dict) else {}
        if isinstance(sliders, dict):
            for slider_name, slider_value in sliders.items():
                try:
                    row[f"slider::{slider_name}"] = float(slider_value)
                except (TypeError, ValueError):
                    continue

        fixed_tags = entry.get("fixed_tags", {}) if isinstance(entry, dict) else {}
        if isinstance(fixed_tags, dict):
            for category, tag_name in fixed_tags.items():
                row[f"tag::{category}::{tag_name}"] = 1.0

        slider_delta = delta.get("slider_delta", {}) if isinstance(delta, dict) else {}
        if isinstance(slider_delta, dict):
            for slider_name, slider_value in slider_delta.items():
                try:
                    row[f"delta::{slider_name}"] = float(slider_value)
                except (TypeError, ValueError):
                    continue

        try:
            pnl = float(history.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0

        feature_rows.append(row)
        pnl_values.append(pnl)

    return feature_rows, pnl_values


def _xgboost_shap_metrics(histories: list[dict[str, Any]]) -> dict[str, Any]:
    feature_rows, pnl_values = _feature_rows(histories)
    if len(feature_rows) < 8:
        raise ValueError("Insufficient samples for xgboost/shap")

    try:
        import numpy as np
        import shap  # type: ignore
        from xgboost import XGBRegressor  # type: ignore
    except Exception as exc:
        raise ValueError("xgboost/shap not available") from exc

    feature_names = sorted({name for row in feature_rows for name in row.keys()})
    if not feature_names:
        raise ValueError("No feature columns available")

    matrix = np.array(
        [[float(row.get(name, 0.0)) for name in feature_names] for row in feature_rows],
        dtype=float,
    )
    targets = np.array(pnl_values, dtype=float)

    model = XGBRegressor(
        n_estimators=120,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=42,
        objective="reg:squarederror",
    )
    model.fit(matrix, targets)

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(matrix)
    if len(getattr(shap_values, "shape", [])) == 1:
        shap_values = shap_values.reshape(-1, 1)

    mean_abs = np.mean(np.abs(shap_values), axis=0)

    details: list[dict[str, Any]] = []
    for index, feature_name in enumerate(feature_names):
        feature_column = matrix[:, index]
        direction = _pearson(feature_column.tolist(), targets.tolist())
        signed_impact = float(mean_abs[index]) * (1.0 if direction >= 0 else -1.0)
        details.append(
            {
                "feature": feature_name,
                "impact": round(signed_impact, 6),
                "support": int(len(feature_rows)),
                "kind": "shap",
            }
        )

    ordered = sorted(details, key=lambda item: item["impact"], reverse=True)
    return {
        "source": "xgboost_shap",
        "sample_count": len(feature_rows),
        "top_positive": ordered[:5],
        "top_negative": sorted(details, key=lambda item: item["impact"])[:5],
        "details": sorted(details, key=lambda item: abs(item["impact"]), reverse=True)[:20],
    }


def _proxy_feature_metrics(histories: list[dict[str, Any]]) -> dict[str, Any]:
    feature_rows, pnl_values = _feature_rows(histories)
    if not feature_rows:
        return {
            "source": "proxy_correlation",
            "sample_count": 0,
            "top_positive": [],
            "top_negative": [],
            "details": [],
        }

    details: list[dict[str, Any]] = []

    numeric_feature_values: dict[str, list[float]] = defaultdict(list)
    numeric_targets: dict[str, list[float]] = defaultdict(list)
    binary_feature_pnls: dict[str, list[float]] = defaultdict(list)

    global_mean_pnl = _safe_mean(pnl_values)

    for row, pnl in zip(feature_rows, pnl_values):
        for name, value in row.items():
            if name.startswith("tag::"):
                if value > 0:
                    binary_feature_pnls[name].append(pnl)
                continue

            numeric_feature_values[name].append(float(value))
            numeric_targets[name].append(pnl)

    for feature_name, values in numeric_feature_values.items():
        correlation = _pearson(values, numeric_targets[feature_name])
        details.append(
            {
                "feature": feature_name,
                "impact": round(correlation, 6),
                "support": len(values),
                "kind": "correlation",
            }
        )

    for feature_name, observed in binary_feature_pnls.items():
        uplift = _safe_mean(observed) - global_mean_pnl
        details.append(
            {
                "feature": feature_name,
                "impact": round(uplift, 6),
                "support": len(observed),
                "kind": "uplift",
            }
        )

    ordered_positive = sorted(details, key=lambda item: item["impact"], reverse=True)
    ordered_negative = sorted(details, key=lambda item: item["impact"])

    return {
        "source": "proxy_correlation",
        "sample_count": len(feature_rows),
        "top_positive": ordered_positive[:5],
        "top_negative": ordered_negative[:5],
        "details": sorted(details, key=lambda item: abs(item["impact"]), reverse=True)[:20],
    }


def build_feature_importance_metrics(histories: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        return _xgboost_shap_metrics(histories)
    except Exception:
        return _proxy_feature_metrics(histories)


def _entry_embedding_vector(trade: Trade) -> list[float]:
    if not trade.embeddings:
        return []

    entry_rows = [row for row in trade.embeddings if row.node_type == "entry"]
    selected_row = entry_rows[0] if entry_rows else trade.embeddings[0]

    if not isinstance(selected_row.vector, list) or not selected_row.vector:
        return []

    try:
        return [float(item) for item in selected_row.vector]
    except (TypeError, ValueError):
        return []


def _daily_key(trade: Trade) -> str:
    closed_at = _to_utc_datetime(trade.closed_at)
    return closed_at.strftime("%Y-%m-%d")


def compute_behavioral_drift(trades: list[Trade], profile_key: str, db: Session) -> dict[str, Any]:
    profile = get_or_create_behavioral_profile(db=db, profile_key=profile_key)

    sweet_raw = profile.sweet_spot_centroid if isinstance(profile.sweet_spot_centroid, list) else []
    danger_raw = profile.danger_zone_centroid if isinstance(profile.danger_zone_centroid, list) else []

    try:
        sweet = [float(item) for item in sweet_raw]
    except (TypeError, ValueError):
        sweet = []
    try:
        danger = [float(item) for item in danger_raw]
    except (TypeError, ValueError):
        danger = []

    sweet_scores: list[float] = []
    danger_scores: list[float] = []

    by_day: dict[str, dict[str, float]] = defaultdict(lambda: {"sweet": 0.0, "danger": 0.0, "count": 0.0})

    for trade in trades:
        vector = _entry_embedding_vector(trade)
        if not vector:
            continue

        sweet_similarity = cosine_similarity(vector, sweet) if sweet else 0.0
        danger_similarity = cosine_similarity(vector, danger) if danger else 0.0

        sweet_scores.append(sweet_similarity)
        danger_scores.append(danger_similarity)

        key = _daily_key(trade)
        by_day[key]["sweet"] += sweet_similarity
        by_day[key]["danger"] += danger_similarity
        by_day[key]["count"] += 1.0

    series: list[dict[str, Any]] = []
    for day in sorted(by_day.keys()):
        count = max(1.0, by_day[day]["count"])
        avg_sweet = by_day[day]["sweet"] / count
        avg_danger = by_day[day]["danger"] / count
        series.append(
            {
                "date": day,
                "trade_count": int(by_day[day]["count"]),
                "avg_sweet_similarity": round(avg_sweet, 4),
                "avg_danger_similarity": round(avg_danger, 4),
                "drift_index": round(avg_danger - avg_sweet, 4),
            }
        )

    avg_sweet = _safe_mean(sweet_scores)
    avg_danger = _safe_mean(danger_scores)

    return {
        "profile_key": profile.profile_key,
        "sweet_spot": {
            "dimension": len(sweet),
            "norm": round(_vector_norm(sweet), 6),
            "preview": [round(item, 6) for item in sweet[:8]],
        },
        "danger_zone": {
            "dimension": len(danger),
            "norm": round(_vector_norm(danger), 6),
            "preview": [round(item, 6) for item in danger[:8]],
        },
        "avg_sweet_similarity": round(avg_sweet, 4),
        "avg_danger_similarity": round(avg_danger, 4),
        "avg_drift_index": round(avg_danger - avg_sweet, 4),
        "series": series,
    }


def _feature_name_to_label(name: str) -> str:
    if name.startswith("slider::"):
        return name.replace("slider::", "Entry slider ", 1)
    if name.startswith("delta::"):
        return name.replace("delta::", "Entry->Exit delta ", 1)
    if name.startswith("tag::"):
        _, category, value = name.split("::", 2)
        return f"Entry tag {category}={value}"
    return name


def _openai_chat_completion(messages: list[dict[str, str]]) -> tuple[str, str, str]:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    payload = {
        "model": settings.retrospective_llm_model,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": 1200,
    }

    req = urllib_request.Request(
        url=f"{settings.openai_base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=settings.retrospective_llm_timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc

    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("OpenAI response missing choices")

    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI response missing text content")

    return content.strip(), settings.retrospective_llm_model, "openai"


def _azure_openai_chat_completion(messages: list[dict[str, str]]) -> tuple[str, str, str]:
    if not settings.azure_openai_endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
    if not settings.azure_openai_api_key:
        raise RuntimeError("AZURE_OPENAI_API_KEY is not configured")
    if not settings.azure_openai_chat_deployment:
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is not configured")

    endpoint = (
        f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
        f"{settings.azure_openai_chat_deployment}/chat/completions"
        f"?api-version={settings.azure_openai_api_version}"
    )

    payload = {
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": 1200,
    }

    req = urllib_request.Request(
        url=endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "api-key": settings.azure_openai_api_key,
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=settings.retrospective_llm_timeout_seconds) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI HTTP {exc.code}: {detail}") from exc

    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Azure OpenAI response missing choices")

    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Azure OpenAI response missing text content")

    return content.strip(), settings.azure_openai_chat_deployment, "azure_openai"


def _fallback_markdown(
    timeframe_days: int,
    period_start: datetime,
    period_end: datetime,
    histories: list[dict[str, Any]],
    feature_importance: dict[str, Any],
    drift: dict[str, Any],
) -> str:
    slider_delta = _average_slider_delta(histories)
    top_negative = feature_importance.get("top_negative", [])
    top_positive = feature_importance.get("top_positive", [])

    lines: list[str] = []
    lines.append("# Retrospective Analysis")
    lines.append("")
    lines.append("## Weekly Snapshot")
    lines.append(f"- Timeframe: last {timeframe_days} day(s)")
    lines.append(f"- Window: {period_start.date().isoformat()} to {period_end.date().isoformat()}")
    lines.append(f"- Completed trades analyzed: {len(histories)}")
    lines.append(f"- Avg sweet-spot similarity: {drift.get('avg_sweet_similarity', 0.0)}")
    lines.append(f"- Avg danger-zone similarity: {drift.get('avg_danger_similarity', 0.0)}")
    lines.append(f"- Drift index (danger-sweet): {drift.get('avg_drift_index', 0.0)}")
    lines.append("")

    lines.append("## Deviations From Sweet Spot")
    if not slider_delta:
        lines.append("- Not enough entry/exit slider pairs to compute drift deltas.")
    else:
        for slider_name, value in slider_delta.items():
            direction = "up" if value > 0 else "down"
            lines.append(f"- {slider_name} shifted {direction} by {abs(value):.2f} on average from entry to exit.")
    lines.append("")

    lines.append("## Feature Signals")
    if top_positive:
        lines.append("- Positive signals:")
        for item in top_positive[:3]:
            label = _feature_name_to_label(str(item.get("feature") or "unknown"))
            lines.append(f"  - {label} ({item.get('impact')})")
    if top_negative:
        lines.append("- Negative signals:")
        for item in top_negative[:3]:
            label = _feature_name_to_label(str(item.get("feature") or "unknown"))
            lines.append(f"  - {label} ({item.get('impact')})")
    if not top_positive and not top_negative:
        lines.append("- Feature signal extraction needs more completed trades.")
    lines.append("")

    lines.append("## Concrete Rules For Next Week")
    lines.append("- Keep entry stress <= 6 and confidence >= 5 before opening new risk.")
    lines.append("- If danger similarity exceeds sweet similarity during pre-trade review, reduce size or skip.")
    lines.append("- Review top negative features before market open and define a counter-action for each.")
    lines.append("- Preserve the strongest positive tag/slider patterns from the last winning cluster.")
    lines.append("- End each day by logging one preventable deviation and one repeatable strength.")
    lines.append("")
    lines.append("_Generated with deterministic fallback synthesis._")

    return "\n".join(lines)


def _synthesis_messages(
    timeframe_days: int,
    period_start: datetime,
    period_end: datetime,
    histories: list[dict[str, Any]],
    feature_importance: dict[str, Any],
    drift: dict[str, Any],
) -> list[dict[str, str]]:
    compact_histories = histories[: min(80, len(histories))]
    payload = {
        "timeframe_days": timeframe_days,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "trade_count": len(histories),
        "trade_histories": compact_histories,
        "feature_importance": feature_importance,
        "behavioral_drift": drift,
    }

    return [
        {
            "role": "system",
            "content": (
                "You are a trading performance reviewer. Produce concise markdown with the sections: "
                "Weekly Snapshot, Deviations From Sweet Spot, Concrete Rules For Next Week. "
                "Rules must be specific, measurable, and tied directly to provided data."
            ),
        },
        {
            "role": "user",
            "content": (
                "Analyze the following structured retrospective payload and return only markdown:\n"
                f"{json.dumps(payload, ensure_ascii=True)}"
            ),
        },
    ]


def generate_retrospective_markdown(
    timeframe_days: int,
    period_start: datetime,
    period_end: datetime,
    histories: list[dict[str, Any]],
    feature_importance: dict[str, Any],
    drift: dict[str, Any],
) -> tuple[str, str, str]:
    messages = _synthesis_messages(
        timeframe_days=timeframe_days,
        period_start=period_start,
        period_end=period_end,
        histories=histories,
        feature_importance=feature_importance,
        drift=drift,
    )

    provider = settings.retrospective_llm_provider
    try:
        if provider == "azure_openai":
            return _azure_openai_chat_completion(messages)
        if provider == "openai":
            return _openai_chat_completion(messages)

        try:
            return _azure_openai_chat_completion(messages)
        except Exception:
            return _openai_chat_completion(messages)
    except Exception:
        fallback = _fallback_markdown(
            timeframe_days=timeframe_days,
            period_start=period_start,
            period_end=period_end,
            histories=histories,
            feature_importance=feature_importance,
            drift=drift,
        )
        return fallback, "fallback-template", "fallback"


def run_retrospective_analysis(
    db: Session,
    timeframe_days: int,
    profile_key: str,
) -> dict[str, Any]:
    retriever = TimeframeTradeRetriever(
        db=db,
        timeframe_days=timeframe_days,
        profile_key=profile_key,
        max_trades=settings.retrospective_max_trades,
    )

    histories = retriever.trade_histories
    documents = retriever.get_relevant_documents(query="weekly retrospective")

    feature_importance = build_feature_importance_metrics(histories)
    drift = compute_behavioral_drift(
        trades=retriever.trade_rows,
        profile_key=retriever.profile_key,
        db=db,
    )

    markdown, synthesis_model, synthesis_source = generate_retrospective_markdown(
        timeframe_days=retriever.timeframe_days,
        period_start=retriever.period_start,
        period_end=retriever.period_end,
        histories=histories,
        feature_importance=feature_importance,
        drift=drift,
    )

    retrieval_summary = {
        "timeframe_days": retriever.timeframe_days,
        "period_start": retriever.period_start.isoformat(),
        "period_end": retriever.period_end.isoformat(),
        "trade_count": len(histories),
        "document_count": len(documents),
        "trade_ids": [item["trade_id"] for item in histories],
        "slider_delta_averages": _average_slider_delta(histories),
    }

    stored_retrieval = dict(retrieval_summary)

    report = RetrospectiveReport(
        profile_key=retriever.profile_key,
        timeframe_days=retriever.timeframe_days,
        period_start=retriever.period_start,
        period_end=retriever.period_end,
        trade_count=len(histories),
        synthesis_model=synthesis_model,
        synthesis_source=synthesis_source,
        report_markdown=markdown,
        retrieval_summary=stored_retrieval,
        feature_metrics=feature_importance,
        drift_metrics=drift,
    )
    db.add(report)
    db.flush()
    db.refresh(report)

    return {
        "report": serialize_retrospective_report(report, include_payload=True),
        "retrieval": {
            **retrieval_summary,
            "histories": histories,
        },
        "feature_importance": feature_importance,
        "drift": drift,
    }
