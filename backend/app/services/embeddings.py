from __future__ import annotations

import base64
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from sqlalchemy.orm import Session

from app.config import settings
from app.models import BehavioralProfile, NodeEmbedding, Trade, TradeNode


@dataclass
class EmbeddingPayload:
    vector: list[float]
    provider: str
    model: str


def _unit_normalize(values: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(item * item for item in values))
    if magnitude == 0:
        return values
    return [item / magnitude for item in values]


def _deterministic_embedding(text: str, dimensions: int) -> EmbeddingPayload:
    safe_dimensions = max(8, dimensions)
    values: list[float] = []
    for index in range(safe_dimensions):
        digest = hashlib.sha256(f"{text}|{index}".encode("utf-8")).digest()
        as_int = int.from_bytes(digest[:8], byteorder="big", signed=False)
        scaled = (as_int / float(2**64 - 1)) * 2.0 - 1.0
        values.append(scaled)
    return EmbeddingPayload(
        vector=_unit_normalize(values),
        provider="deterministic",
        model="deterministic-hash-v1",
    )


def _build_azure_embedding_url() -> str:
    return (
        f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
        f"{settings.azure_openai_embedding_deployment}/embeddings"
        f"?api-version={settings.azure_openai_api_version}"
    )


def _azure_openai_embedding(text: str) -> EmbeddingPayload:
    if not settings.azure_openai_endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured")
    if not settings.azure_openai_api_key:
        raise RuntimeError("AZURE_OPENAI_API_KEY is not configured")
    if not settings.azure_openai_embedding_deployment:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not configured")

    payload = json.dumps({"input": text}).encode("utf-8")
    req = urllib_request.Request(
        url=_build_azure_embedding_url(),
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "api-key": settings.azure_openai_api_key,
        },
    )

    with urllib_request.urlopen(req, timeout=12) as response:
        body = json.loads(response.read().decode("utf-8"))

    data = body.get("data")
    if not isinstance(data, list) or not data:
        raise RuntimeError("Azure OpenAI response missing embedding data")

    embedding = data[0].get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Azure OpenAI response has invalid embedding payload")

    vector = [float(item) for item in embedding]
    return EmbeddingPayload(
        vector=vector,
        provider="azure_openai",
        model=settings.embedding_model,
    )


def generate_embedding(text: str) -> EmbeddingPayload:
    provider = settings.embedding_provider
    if provider == "azure_openai":
        try:
            return _azure_openai_embedding(text)
        except Exception:
            fallback = _deterministic_embedding(text, settings.embedding_dimensions)
            fallback.provider = "deterministic_fallback"
            return fallback

    return _deterministic_embedding(text, settings.embedding_dimensions)


def _opensearch_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.opensearch_username:
        token = base64.b64encode(
            f"{settings.opensearch_username}:{settings.opensearch_password}".encode("utf-8")
        ).decode("utf-8")
        headers["Authorization"] = f"Basic {token}"
    return headers


def _opensearch_request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    if not settings.opensearch_url:
        return 0, "OPENSEARCH_URL is not configured"

    url = f"{settings.opensearch_url.rstrip('/')}/{path.lstrip('/')}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(url=url, method=method, data=body, headers=_opensearch_headers())

    try:
        with urllib_request.urlopen(req, timeout=8) as response:
            return response.status, response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")
    except Exception as exc:
        return 0, str(exc)


def _ensure_opensearch_index(dimension: int) -> tuple[bool, str | None]:
    head_status, head_body = _opensearch_request("HEAD", settings.opensearch_index)
    if head_status == 200:
        return True, None
    if head_status not in (0, 404):
        return False, f"HEAD index failed: {head_status} {head_body}"

    index_payload = {
        "settings": {
            "index": {
                "knn": True,
            }
        },
        "mappings": {
            "properties": {
                "trade_node_id": {"type": "integer"},
                "trade_id": {"type": "integer"},
                "node_type": {"type": "keyword"},
                "embedding_model": {"type": "keyword"},
                "embedding_provider": {"type": "keyword"},
                "embedding_dimension": {"type": "integer"},
                "serialized_state": {"type": "text"},
                "pnl": {"type": "float"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": max(1, int(dimension)),
                },
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
            }
        },
    }
    create_status, create_body = _opensearch_request("PUT", settings.opensearch_index, payload=index_payload)
    if create_status in (200, 201):
        return True, None

    if create_status == 400 and "resource_already_exists_exception" in create_body:
        return True, None

    return False, f"Failed to create index: {create_status} {create_body}"


def _sync_to_opensearch(row: NodeEmbedding) -> tuple[bool, str | None, str | None]:
    index_ok, index_error = _ensure_opensearch_index(row.embedding_dimension)
    if not index_ok:
        return False, None, index_error

    document_id = str(row.trade_node_id)
    payload = {
        "trade_node_id": row.trade_node_id,
        "trade_id": row.trade_id,
        "node_type": row.node_type,
        "embedding_model": row.embedding_model,
        "embedding_provider": row.embedding_provider,
        "embedding_dimension": row.embedding_dimension,
        "serialized_state": row.serialized_state,
        "pnl": row.pnl_at_storage,
        "embedding": row.vector,
        "created_at": row.created_at.isoformat() if row.created_at else datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }

    status, body = _opensearch_request(
        "PUT",
        f"{settings.opensearch_index}/_doc/{document_id}",
        payload=payload,
    )
    if status in (200, 201):
        return True, document_id, None

    return False, document_id, f"OpenSearch upsert failed: {status} {body}"


def sync_embedding_vector_store(row: NodeEmbedding) -> None:
    backend = settings.vector_store_backend
    if backend == "opensearch":
        ok, document_id, error = _sync_to_opensearch(row)
        row.vector_store_backend = "opensearch"
        row.vector_store_synced = ok
        row.vector_store_doc_id = document_id
        row.vector_store_error = error
        return

    row.vector_store_backend = "database"
    row.vector_store_synced = True
    row.vector_store_doc_id = str(row.trade_node_id)
    row.vector_store_error = None


def upsert_node_embedding_for_trade_node(
    db: Session,
    trade: Trade,
    node: TradeNode,
    serialized_state: str,
    embedding_payload: EmbeddingPayload | None = None,
) -> NodeEmbedding:
    embedding = embedding_payload or generate_embedding(serialized_state)

    row = db.query(NodeEmbedding).filter(NodeEmbedding.trade_node_id == node.id).first()
    if row is None:
        row = NodeEmbedding(
            trade_id=trade.id,
            trade_node_id=node.id,
            node_type=node.node_type,
        )
        db.add(row)

    row.trade_id = trade.id
    row.node_type = node.node_type
    row.embedding_model = embedding.model
    row.embedding_provider = embedding.provider
    row.embedding_dimension = len(embedding.vector)
    row.serialized_state = serialized_state
    row.vector = embedding.vector
    row.pnl_at_storage = trade.pnl

    sync_embedding_vector_store(row)
    db.flush()
    return row


def sync_trade_embeddings_with_final_pnl(db: Session, trade_id: int, pnl: float | None) -> int:
    rows = db.query(NodeEmbedding).filter(NodeEmbedding.trade_id == trade_id).all()
    for row in rows:
        row.pnl_at_storage = pnl
        sync_embedding_vector_store(row)
    return len(rows)


def get_or_create_behavioral_profile(
    db: Session,
    profile_key: str = "global",
    user_id: str | None = None,
) -> BehavioralProfile:
    safe_key = (profile_key or "global").strip() or "global"
    row = db.query(BehavioralProfile).filter(BehavioralProfile.profile_key == safe_key).first()
    if row is not None:
        return row

    created = BehavioralProfile(profile_key=safe_key, user_id=(user_id or None))
    db.add(created)
    db.flush()
    return created
