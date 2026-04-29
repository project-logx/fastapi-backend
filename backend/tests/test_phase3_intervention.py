from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models import NodeEmbedding
from app.services.embeddings import generate_embedding, get_or_create_behavioral_profile
from app.services.serialization import serialize_node_state_for_embedding


DEFAULT_SLIDERS = {
    "Confidence": 7,
    "Stress": 8,
    "Focus": 7,
    "Market Clarity": 5,
    "Patience": 5,
}
ENTRY_FIXED_TAGS = {
    "Direction": "Long",
    "Strategy": "Breakout",
    "Market": "trending day",
}


@contextmanager
def _db_session() -> Generator[Session, None, None]:
    provider = app.dependency_overrides.get(get_db)
    assert provider is not None
    session_generator = provider()
    db = next(session_generator)
    try:
        yield db
    finally:
        session_generator.close()


def _inject_entry(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "quantity": 20,
            "average_price": 22100.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _first_pending_entry_id(client: TestClient) -> int:
    response = client.get("/api/v1/queue/pending")
    assert response.status_code == 200
    rows = response.json()["data"]["pending_entry"]
    assert rows
    return rows[0]["id"]


def _payload(note: str, confirm: bool = False) -> dict[str, str]:
    return {
        "type": "entry",
        "captured_at": datetime.now(UTC).isoformat(),
        "fixed_tags": json.dumps(ENTRY_FIXED_TAGS),
        "custom_tag_ids": json.dumps([]),
        "sliders": json.dumps(DEFAULT_SLIDERS),
        "note": note,
        "confirm_intervention": "true" if confirm else "false",
    }


def _set_profile_danger_centroid(vector: list[float]) -> None:
    with _db_session() as db:
        profile = get_or_create_behavioral_profile(db=db, profile_key=settings.intervention_profile_key)
        profile.danger_zone_centroid = vector
        db.commit()


def _state_embedding_for(note: str) -> list[float]:
    serialized = serialize_node_state_for_embedding(
        node_type="entry",
        sliders=DEFAULT_SLIDERS,
        fixed_tags=ENTRY_FIXED_TAGS,
        note=note,
    )
    return generate_embedding(serialized).vector


def test_entry_node_requires_confirmation_when_danger_similarity_is_high(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    note = "revenge impulse setup"
    _set_profile_danger_centroid(_state_embedding_for(note))

    response = client.post(f"/api/v1/trades/{trade_id}/nodes", data=_payload(note=note, confirm=False))
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["status"] == "intervention_required"
    assert data["requires_confirmation"] is True
    assert "intervention" in data
    assert data["intervention"]["similarity"] >= data["intervention"]["threshold"]
    assert data["intervention"]["message"]

    trade_detail = client.get(f"/api/v1/trades/{trade_id}")
    assert trade_detail.status_code == 200
    assert trade_detail.json()["data"]["nodes"] == []

    with _db_session() as db:
        assert db.query(NodeEmbedding).filter(NodeEmbedding.trade_id == trade_id).count() == 0


def test_confirm_intervention_commits_node_and_embedding(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    note = "pressure entry, ignore plan"
    _set_profile_danger_centroid(_state_embedding_for(note))

    first = client.post(f"/api/v1/trades/{trade_id}/nodes", data=_payload(note=note, confirm=False))
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "intervention_required"

    second = client.post(f"/api/v1/trades/{trade_id}/nodes", data=_payload(note=note, confirm=True))
    assert second.status_code == 200
    assert second.json()["data"]["node"]["type"] == "entry"
    assert second.json()["data"]["trade"]["status"] == "active"

    with _db_session() as db:
        assert db.query(NodeEmbedding).filter(NodeEmbedding.trade_id == trade_id).count() == 1


def test_entry_submits_normally_when_similarity_is_below_threshold(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    note = "structured calm entry"
    baseline_vector = _state_embedding_for(note)
    _set_profile_danger_centroid([-value for value in baseline_vector])

    response = client.post(f"/api/v1/trades/{trade_id}/nodes", data=_payload(note=note, confirm=False))
    assert response.status_code == 200
    assert response.json()["data"]["node"]["type"] == "entry"
    assert response.json()["data"]["trade"]["status"] == "active"
