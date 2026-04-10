from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x89\x93\xa7"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _capture_payload(node_type: str, custom_tag_ids: list[int] | None = None, tags: list[str] | None = None) -> dict[str, str]:
    return {
        "type": node_type,
        "captured_at": datetime.now(UTC).isoformat(),
        "tags": json.dumps(tags or []),
        "custom_tag_ids": json.dumps(custom_tag_ids or []),
        "sliders": json.dumps(
            {
                "Confidence": 7,
                "Stress": 3,
                "Focus": 8,
                "Market Clarity": 6,
                "Patience": 5,
            }
        ),
        "note": f"{node_type} node",
    }


def _create_custom_tag(client: TestClient, name: str = "high_conviction") -> int:
    response = client.post("/api/v1/tags/custom", json={"name": name, "category": "strategy"})
    assert response.status_code in (200, 201)
    return response.json()["data"]["id"]


def _inject_entry(client: TestClient, event_id: str | None = None) -> None:
    payload = {
        "symbol": "NIFTY24APR-FUT",
        "product": "MIS",
        "quantity": 50,
        "average_price": 22100.0,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if event_id:
        payload["event_id"] = event_id

    response = client.post("/api/v1/mock/events/entry", json=payload)
    assert response.status_code == 200


def _inject_exit(client: TestClient, event_id: str | None = None) -> None:
    payload = {
        "symbol": "NIFTY24APR-FUT",
        "product": "MIS",
        "average_price": 22130.0,
        "pnl": 1500.0,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if event_id:
        payload["event_id"] = event_id

    response = client.post("/api/v1/mock/events/exit", json=payload)
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


def test_health_and_capture_config(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["data"]["status"] == "ok"

    metadata = client.get("/api/v1/metadata/capture-config")
    assert metadata.status_code == 200
    data = metadata.json()["data"]
    assert "sliders" in data
    assert "allowed_tags" in data
    assert "entry" in data["allowed_tags"]
    assert "exit" in data["allowed_tags"]


def test_mock_entry_creates_pending_entry_and_duplicate_is_deduped(client: TestClient) -> None:
    _inject_entry(client, event_id="evt-entry-1")

    queue = client.get("/api/v1/queue/pending")
    assert queue.status_code == 200
    assert len(queue.json()["data"]["pending_entry"]) == 1

    duplicate = client.post(
        "/api/v1/mock/events/entry",
        json={
            "event_id": "evt-entry-1",
            "symbol": "NIFTY24APR-FUT",
            "product": "MIS",
            "quantity": 50,
            "average_price": 22100.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["status"] == "duplicate"

    queue_after = client.get("/api/v1/queue/pending")
    assert queue_after.status_code == 200
    assert len(queue_after.json()["data"]["pending_entry"]) == 1


def test_full_lifecycle_with_mid_exit_and_journey_replay(client: TestClient) -> None:
    tag_id = _create_custom_tag(client)

    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    entry_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("entry", custom_tag_ids=[tag_id], tags=["Long", "Breakout", "trending day"]),
        files=[("files", ("entry.png", PNG_BYTES, "image/png"))],
    )
    assert entry_response.status_code == 200
    node_data = entry_response.json()["data"]["node"]
    assert node_data["type"] == "entry"
    assert node_data["attachments"]

    active = client.get("/api/v1/trades/active")
    assert active.status_code == 200
    assert len(active.json()["data"]) == 1

    mid_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("mid", custom_tag_ids=[tag_id], tags=["Short", "Reversal", "Range day"]),
        files=[("files", ("mid.png", PNG_BYTES, "image/png"))],
    )
    assert mid_response.status_code == 200
    assert mid_response.json()["data"]["node"]["type"] == "mid"

    _inject_exit(client)
    exit_trade_id = _first_pending_exit_id(client)
    assert exit_trade_id == trade_id

    exit_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("exit", custom_tag_ids=[tag_id], tags=["Perfect exit", "a+", "Target hit"]),
        files=[("files", ("exit.png", PNG_BYTES, "image/png"))],
    )
    assert exit_response.status_code == 200
    assert exit_response.json()["data"]["trade"]["status"] == "complete"

    journeys = client.get("/api/v1/journeys")
    assert journeys.status_code == 200
    assert journeys.json()["meta"]["count"] == 1

    journey_id = journeys.json()["data"][0]["id"]
    replay = client.get(f"/api/v1/journeys/{journey_id}")
    assert replay.status_code == 200
    nodes = replay.json()["data"]["nodes"]
    assert [node["type"] for node in nodes] == ["entry", "mid", "exit"]


def test_attachment_endpoints_and_immutability(client: TestClient) -> None:
    _inject_entry(client)
    trade_id = _first_pending_entry_id(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("entry", tags=["Short", "Pullback", "News driven"]),
        files=[("files", ("entry.png", PNG_BYTES, "image/png"))],
    )
    assert response.status_code == 200

    node = response.json()["data"]["node"]
    node_id = node["id"]
    attachment_id = node["attachments"][0]["id"]

    listed = client.get(f"/api/v1/trades/{trade_id}/nodes/{node_id}/attachments")
    assert listed.status_code == 200
    assert listed.json()["meta"]["count"] == 1

    fetched = client.get(f"/api/v1/attachments/{attachment_id}")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("image/png")

    deleted = client.delete(f"/api/v1/attachments/{attachment_id}")
    assert deleted.status_code == 200

    # Re-add attachment and complete journey to test immutable delete guard.
    response_2 = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("mid", tags=["Long", "Price action", "trending day"]),
        files=[("files", ("mid.png", PNG_BYTES, "image/png"))],
    )
    assert response_2.status_code == 200

    _inject_exit(client)
    pending_exit_id = _first_pending_exit_id(client)
    assert pending_exit_id == trade_id

    exit_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data=_capture_payload("exit", tags=["Perfect exit", "a+", "Target hit"]),
        files=[("files", ("exit.png", PNG_BYTES, "image/png"))],
    )
    assert exit_response.status_code == 200
    exit_attachment_id = exit_response.json()["data"]["node"]["attachments"][0]["id"]

    blocked_delete = client.delete(f"/api/v1/attachments/{exit_attachment_id}")
    assert blocked_delete.status_code == 409
