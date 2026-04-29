from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.main import app
from app.models import BehavioralProfile, NodeEmbedding
from app.services.embeddings import get_or_create_behavioral_profile
from app.services.serialization import serialize_node_state_for_embedding


DEFAULT_SLIDERS = {
    "Confidence": 7,
    "Stress": 3,
    "Focus": 8,
    "Market Clarity": 6,
    "Patience": 5,
}
ENTRY_FIXED_TAGS = {
    "Direction": "Long",
    "Strategy": "Breakout",
    "Market": "trending day",
}
MID_FIXED_TAGS = {
    "Direction": "Short",
    "Strategy": "Reversal",
    "Market": "Range day",
}
EXIT_FIXED_TAGS = {
    "Execution": "Perfect exit",
    "Quality": "a+",
    "Outcome": "Target hit",
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


def _capture_payload(node_type: str, fixed_tags: dict[str, str], note: str) -> dict[str, str]:
    return {
        "type": node_type,
        "captured_at": datetime.now(UTC).isoformat(),
        "fixed_tags": json.dumps(fixed_tags),
        "tags": json.dumps([]),
        "custom_tag_ids": json.dumps([]),
        "sliders": json.dumps(DEFAULT_SLIDERS),
        "note": note,
    }


def _inject_entry(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "quantity": 10,
            "average_price": 22100.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _inject_exit(client: TestClient, pnl: float) -> None:
    response = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "average_price": 22130.0,
            "pnl": pnl,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _first_pending_trade_id(client: TestClient, queue_key: str) -> int:
    response = client.get("/api/v1/queue/pending")
    assert response.status_code == 200
    rows = response.json()["data"][queue_key]
    assert rows
    return rows[0]["id"]


def _submit_node(client: TestClient, trade_id: int, payload: dict[str, str]) -> dict:
    response = client.post(f"/api/v1/trades/{trade_id}/nodes", data=payload)
    assert response.status_code == 200
    return response.json()["data"]["node"]


def test_embedding_serialization_is_dense_and_deterministic() -> None:
    text = serialize_node_state_for_embedding(
        node_type="entry",
        sliders={
            "Patience": 5,
            "Focus": 8,
            "Confidence": 7,
            "Market Clarity": 6,
            "Stress": 3,
        },
        fixed_tags={
            "Strategy": "Breakout",
            "Direction": "Long",
            "Market": "trending day",
        },
        note="  calm  \n execution   ",
    )

    assert text == (
        "node_type=entry || "
        "fixed_tags=Direction:Long|Strategy:Breakout|Market:trending day || "
        "sliders=Confidence:7|Stress:3|Focus:8|Market Clarity:6|Patience:5 || "
        "note=calm execution"
    )


def test_entry_and_mid_nodes_generate_and_store_embeddings(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")

    entry_node = _submit_node(
        client,
        trade_id,
        _capture_payload("entry", ENTRY_FIXED_TAGS, "entry reflection"),
    )
    mid_node = _submit_node(
        client,
        trade_id,
        _capture_payload("mid", MID_FIXED_TAGS, "mid reflection"),
    )

    with _db_session() as db:
        rows = db.query(NodeEmbedding).filter(NodeEmbedding.trade_id == trade_id).all()
        assert len(rows) == 2

        entry_row = next(row for row in rows if row.trade_node_id == entry_node["id"])
        mid_row = next(row for row in rows if row.trade_node_id == mid_node["id"])

        assert entry_row.node_type == "entry"
        assert mid_row.node_type == "mid"

        assert isinstance(entry_row.vector, list)
        assert isinstance(mid_row.vector, list)
        assert len(entry_row.vector) == entry_row.embedding_dimension > 0
        assert len(mid_row.vector) == mid_row.embedding_dimension > 0

        assert "entry reflection" in entry_row.serialized_state
        assert "mid reflection" in mid_row.serialized_state


@pytest.mark.parametrize("pnl", [1500.0, -420.5])
def test_exit_node_updates_eventual_pnl_for_existing_embeddings(client: TestClient, pnl: float) -> None:
    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")

    _submit_node(client, trade_id, _capture_payload("entry", ENTRY_FIXED_TAGS, "entry note"))
    _submit_node(client, trade_id, _capture_payload("mid", MID_FIXED_TAGS, "mid note"))

    _inject_exit(client, pnl=pnl)
    pending_exit_trade_id = _first_pending_trade_id(client, "pending_exit")
    assert pending_exit_trade_id == trade_id

    _submit_node(client, trade_id, _capture_payload("exit", EXIT_FIXED_TAGS, "exit note"))

    with _db_session() as db:
        rows = db.query(NodeEmbedding).filter(NodeEmbedding.trade_id == trade_id).all()
        assert len(rows) == 2
        assert all(row.pnl_at_storage == pnl for row in rows)
        assert all(row.vector_store_backend in {"database", "opensearch"} for row in rows)


def test_opensearch_backend_failure_is_non_blocking_and_recorded(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "vector_store_backend", "opensearch")
    monkeypatch.setattr(settings, "opensearch_url", "")

    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")
    entry_node = _submit_node(client, trade_id, _capture_payload("entry", ENTRY_FIXED_TAGS, "entry note"))

    with _db_session() as db:
        row = db.query(NodeEmbedding).filter(NodeEmbedding.trade_node_id == entry_node["id"]).first()
        assert row is not None
        assert row.vector_store_backend == "opensearch"
        assert row.vector_store_synced is False
        assert row.vector_store_error
        assert "OPENSEARCH_URL" in row.vector_store_error


def test_behavioral_profile_table_supports_global_profile(client: TestClient) -> None:
    with _db_session() as db:
        created = get_or_create_behavioral_profile(db, profile_key="global")
        db.commit()

        fetched = db.query(BehavioralProfile).filter(BehavioralProfile.profile_key == "global").first()
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.sweet_spot_centroid == []
        assert fetched.danger_zone_centroid == []

        same = get_or_create_behavioral_profile(db, profile_key="global")
        assert same.id == created.id
