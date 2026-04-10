from __future__ import annotations

from datetime import UTC, datetime

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


def _inject_exit(client: TestClient) -> None:
    response = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "average_price": 22140.0,
            "pnl": 1250.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _first_pending_entry_id(client: TestClient) -> int:
    response = client.get("/api/v1/queue/pending")
    assert response.status_code == 200
    data = response.json()["data"]["pending_entry"]
    assert data
    return data[0]["id"]


def _first_pending_exit_id(client: TestClient) -> int:
    response = client.get("/api/v1/queue/pending")
    assert response.status_code == 200
    data = response.json()["data"]["pending_exit"]
    assert data
    return data[0]["id"]


def test_docs_entry_capture_endpoint_accepts_structured_fields(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes/entry",
        data={
            "direction": "Long",
            "strategy": "Breakout",
            "market_context": "trending day",
            "confidence": 7,
            "stress": 3,
            "focus": 8,
            "market_clarity": 6,
            "patience": 5,
            "note": "entry via docs",
        },
    )

    assert response.status_code == 200
    node = response.json()["data"]["node"]
    assert node["fixed_tags"]["Direction"] == "Long"
    assert node["fixed_tags"]["Strategy"] == "Breakout"
    assert node["fixed_tags"]["Market context"] == "trending day"


def test_docs_exit_capture_endpoint_accepts_structured_fields(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    entry_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes/entry",
        data={
            "direction": "Short",
            "strategy": "Reversal",
            "market_context": "Range day",
            "confidence": 6,
            "stress": 4,
            "focus": 7,
            "market_clarity": 6,
            "patience": 5,
            "note": "entry before exit",
        },
    )
    assert entry_response.status_code == 200

    _inject_exit(client)
    pending_exit_id = _first_pending_exit_id(client)
    assert pending_exit_id == trade_id

    exit_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes/exit",
        data={
            "execution": "Perfect exit",
            "result_quality": "a+",
            "outcome": "Target hit",
            "confidence": 7,
            "stress": 2,
            "focus": 8,
            "market_clarity": 7,
            "patience": 6,
            "note": "exit via docs",
        },
    )

    assert exit_response.status_code == 200
    node = exit_response.json()["data"]["node"]
    assert node["fixed_tags"]["Execution"] == "Perfect exit"
    assert node["fixed_tags"]["Result quality"] == "a+"
    assert node["fixed_tags"]["Outcome"] == "Target hit"
    assert exit_response.json()["data"]["trade"]["status"] == "complete"
