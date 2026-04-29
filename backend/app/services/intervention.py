from __future__ import annotations

import json
import math
from statistics import mean
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import NodeEmbedding, Trade
from app.services.embeddings import get_or_create_behavioral_profile


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def dynamic_intervention_threshold(base_threshold: float, sliders: dict[str, int], quality_score: float) -> float:
    threshold = float(base_threshold)

    stress = int(sliders.get("Stress", 0))
    confidence = int(sliders.get("Confidence", 0))
    market_clarity = int(sliders.get("Market Clarity", 0))

    if stress >= 8:
        threshold -= 0.05
    elif stress >= 6:
        threshold -= 0.02

    if confidence <= 3:
        threshold -= 0.03
    elif confidence <= 5:
        threshold -= 0.01

    if market_clarity <= 3:
        threshold -= 0.03
    elif market_clarity <= 5:
        threshold -= 0.01

    if quality_score < 40:
        threshold -= 0.03
    elif quality_score < 60:
        threshold -= 0.01

    return max(0.70, min(0.95, threshold))


def _find_danger_matches(
    db: Session,
    current_vector: list[float],
    node_type: str,
    top_k: int,
) -> dict[str, Any]:
    rows = (
        db.query(NodeEmbedding)
        .options(joinedload(NodeEmbedding.trade))
        .filter(NodeEmbedding.node_type == node_type)
        .all()
    )

    candidates: list[dict[str, Any]] = []
    for row in rows:
        pnl = row.pnl_at_storage
        if pnl is None and row.trade is not None:
            pnl = row.trade.pnl
        if pnl is None or pnl >= 0:
            continue

        vector = row.vector or []
        if not isinstance(vector, list):
            continue

        try:
            vector_values = [float(item) for item in vector]
        except (TypeError, ValueError):
            continue

        similarity = cosine_similarity(current_vector, vector_values)
        if similarity <= 0:
            continue

        candidates.append(
            {
                "similarity": similarity,
                "trade_id": row.trade_id,
                "trade_node_id": row.trade_node_id,
                "serialized_state": row.serialized_state,
                "pnl": float(pnl),
            }
        )

    if not candidates:
        return {
            "top_match": None,
            "avg_loss": None,
            "top_examples": [],
        }

    sorted_candidates = sorted(candidates, key=lambda item: item["similarity"], reverse=True)
    top_examples = sorted_candidates[: max(1, top_k)]

    avg_loss = mean([abs(example["pnl"]) for example in top_examples])
    return {
        "top_match": top_examples[0],
        "avg_loss": avg_loss,
        "top_examples": top_examples,
    }


def _openai_chat_completion(messages: list[dict[str, str]]) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    payload = {
        "model": settings.intervention_llm_model,
        "messages": messages,
        "temperature": 0.25,
        "max_tokens": 220,
    }
    body = json.dumps(payload).encode("utf-8")

    base_url = settings.openai_base_url.rstrip("/")
    req = urllib_request.Request(
        url=f"{base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.openai_api_key}",
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=settings.intervention_llm_timeout_seconds) as response:
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

    return content.strip()


def _fallback_intervention_message(similarity: float, threshold: float, avg_loss: float | None, note: str | None) -> str:
    avg_loss_text = f"{avg_loss:.2f}" if avg_loss is not None else "unknown"
    current_note = (note or "").strip() or "(no note provided)"
    return (
        "Potential danger-pattern overlap detected. "
        f"Similarity {similarity:.3f} exceeded threshold {threshold:.3f}. "
        f"Average historical loss for similar states: {avg_loss_text}. "
        f"Pause and validate setup quality before continuing. Current note: {current_note}"
    )


def generate_intervention_message(
    similarity: float,
    threshold: float,
    avg_loss: float | None,
    matched_state: str | None,
    current_note: str | None,
) -> tuple[str, str]:
    prompt_payload = {
        "similarity": round(similarity, 4),
        "threshold": round(threshold, 4),
        "average_loss": avg_loss,
        "matched_historical_state": matched_state or "",
        "current_note": (current_note or "").strip(),
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise trading psychology coach. "
                "Return a short intervention in 3 bullet points, each practical and specific. "
                "Avoid generic motivational language and avoid financial advice."
            ),
        },
        {
            "role": "user",
            "content": (
                "Create a localized intervention based on this risk context JSON:\n"
                f"{json.dumps(prompt_payload, ensure_ascii=True)}"
            ),
        },
    ]

    try:
        return _openai_chat_completion(messages), settings.intervention_llm_model
    except Exception:
        return _fallback_intervention_message(similarity, threshold, avg_loss, current_note), "fallback-template"


def evaluate_intervention(
    db: Session,
    trade: Trade,
    node_type: str,
    current_vector: list[float],
    sliders: dict[str, int],
    note: str | None,
) -> dict[str, Any] | None:
    if not settings.intervention_enabled:
        return None

    profile = get_or_create_behavioral_profile(db, profile_key=settings.intervention_profile_key)
    danger_centroid = profile.danger_zone_centroid or []
    if not isinstance(danger_centroid, list) or not danger_centroid:
        return None

    try:
        centroid_vector = [float(item) for item in danger_centroid]
    except (TypeError, ValueError):
        return None

    similarity = cosine_similarity(current_vector, centroid_vector)
    threshold = dynamic_intervention_threshold(
        base_threshold=settings.intervention_similarity_threshold,
        sliders=sliders,
        quality_score=float(trade.computed_quality_score or 0.0),
    )
    if similarity < threshold:
        return None

    danger_matches = _find_danger_matches(
        db=db,
        current_vector=current_vector,
        node_type=node_type,
        top_k=settings.intervention_history_match_count,
    )
    top_match = danger_matches.get("top_match")
    avg_loss = danger_matches.get("avg_loss")

    message, llm_model = generate_intervention_message(
        similarity=similarity,
        threshold=threshold,
        avg_loss=avg_loss,
        matched_state=top_match.get("serialized_state") if isinstance(top_match, dict) else None,
        current_note=note,
    )

    return {
        "requires_confirmation": True,
        "profile_key": profile.profile_key,
        "similarity": round(similarity, 4),
        "threshold": round(threshold, 4),
        "average_loss": round(avg_loss, 4) if isinstance(avg_loss, (int, float)) else None,
        "matched_state": top_match.get("serialized_state") if isinstance(top_match, dict) else None,
        "matched_trade_id": top_match.get("trade_id") if isinstance(top_match, dict) else None,
        "matched_node_id": top_match.get("trade_node_id") if isinstance(top_match, dict) else None,
        "message": message,
        "llm_model": llm_model,
    }
