from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient


def _inject_entry(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "quantity": 50,
            "average_price": 22100.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _inject_exit(client: TestClient, pnl: float = 1800.0) -> None:
    response = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "average_price": 22145.0,
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


def _valid_sliders_json() -> str:
    return json.dumps(
        {
            "Confidence": 7,
            "Stress": 3,
            "Focus": 8,
            "Market Clarity": 6,
            "Patience": 5,
        }
    )


def _submit_node(client: TestClient, trade_id: int, node_type: str, fixed_tags: dict[str, str], note: str) -> dict:
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": node_type,
            "captured_at": datetime.now(UTC).isoformat(),
            "fixed_tags": json.dumps(fixed_tags),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_sliders_json(),
            "note": note,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_taxonomy_seeded_with_expected_weights_and_scores(client: TestClient) -> None:
    response = client.get("/api/v1/tags/categories")
    assert response.status_code == 200

    categories = response.json()["data"]
    assert len(categories) >= 6

    weights = {item["name"]: item["category_weight"] for item in categories}
    assert weights["Direction"] == 5
    assert weights["Strategy"] == 25
    assert weights["Market"] == 15
    assert weights["Execution"] == 30
    assert weights["Quality"] == 20
    assert weights["Outcome"] == 5

    strategy = next(item for item in categories if item["name"] == "Strategy")
    strategy_scores = {tag["name"]: tag["tag_score"] for tag in strategy["tags"]}
    assert strategy_scores["Breakout"] == 8

    quality = next(item for item in categories if item["name"] == "Quality")
    quality_scores = {tag["name"]: tag["tag_score"] for tag in quality["tags"]}
    assert quality_scores["Rule break"] == 5


def test_capture_metadata_exposes_category_weights_and_tag_scores(client: TestClient) -> None:
    response = client.get("/api/v1/metadata/capture-config")
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["category_weights"]["Execution"] == 30
    assert data["category_weights"]["Quality"] == 20
    assert data["fixed_tag_scores_by_category"]["Strategy"]["Breakout"] == 8
    assert data["max_tag_score_by_category"]["Execution"] == 10


def test_trade_score_is_computed_and_reaches_100_for_best_case(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")

    entry_data = _submit_node(
        client,
        trade_id,
        "entry",
        {
            "Direction": "Long",
            "Strategy": "Breakout",
            "Market": "trending day",
        },
        "entry scoring",
    )
    assert entry_data["trade"]["computed_quality_score"] == pytest.approx(45.0)

    _inject_exit(client, pnl=2100.0)
    pending_exit_id = _first_pending_trade_id(client, "pending_exit")
    assert pending_exit_id == trade_id

    exit_data = _submit_node(
        client,
        trade_id,
        "exit",
        {
            "Execution": "Perfect exit",
            "Quality": "a+",
            "Outcome": "Target hit",
        },
        "exit scoring",
    )
    assert exit_data["trade"]["computed_quality_score"] == pytest.approx(100.0)

    journeys = client.get("/api/v1/journeys")
    assert journeys.status_code == 200
    journey_row = journeys.json()["data"][0]
    assert journey_row["computed_quality_score"] == pytest.approx(100.0)


def test_put_trade_recalculates_score_when_tags_change(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")

    entry_data = _submit_node(
        client,
        trade_id,
        "entry",
        {
            "Direction": "Long",
            "Strategy": "Breakout",
            "Market": "trending day",
        },
        "initial",
    )
    node_id = entry_data["node"]["id"]
    assert entry_data["trade"]["computed_quality_score"] == pytest.approx(45.0)

    response = client.put(
        f"/api/v1/trades/{trade_id}",
        json={
            "node_updates": [
                {
                    "node_id": node_id,
                    "fixed_tags": {
                        "Direction": "Long",
                        "Strategy": "Reversal",
                        "Market": "News driven",
                    },
                    "note": "retagged",
                }
            ]
        },
    )
    assert response.status_code == 200

    expected = 5.0 + ((6.0 / 8.0) * 25.0) + ((5.0 / 9.0) * 15.0)
    assert response.json()["data"]["computed_quality_score"] == pytest.approx(expected, rel=1e-4)


def test_put_trade_rejects_invalid_category_for_node_type(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_trade_id(client, "pending_entry")

    entry_data = _submit_node(
        client,
        trade_id,
        "entry",
        {
            "Direction": "Long",
            "Strategy": "Breakout",
            "Market": "trending day",
        },
        "initial",
    )
    node_id = entry_data["node"]["id"]

    response = client.put(
        f"/api/v1/trades/{trade_id}",
        json={
            "node_updates": [
                {
                    "node_id": node_id,
                    "fixed_tags": {
                        "Direction": "Long",
                        "Strategy": "Breakout",
                        "Execution": "Perfect exit",
                    },
                }
            ]
        },
    )
    assert response.status_code == 422


def test_tag_create_accepts_tag_score_schema(client: TestClient) -> None:
    categories_response = client.get("/api/v1/tags/categories")
    assert categories_response.status_code == 200
    strategy_category = next(item for item in categories_response.json()["data"] if item["name"] == "Strategy")

    create_response = client.post(
        "/api/v1/tags",
        json={
            "category_id": strategy_category["id"],
            "name": "Momentum burst",
            "tag_score": 7,
        },
    )
    assert create_response.status_code == 200

    created = create_response.json()["data"]
    assert created["name"] == "Momentum burst"
    assert created["tag_score"] == 7
    assert created["category_id"] == strategy_category["id"]
