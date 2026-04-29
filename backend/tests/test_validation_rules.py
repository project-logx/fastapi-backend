from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _inject_entry(client: TestClient) -> int:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": "BANKNIFTY24APR-FUT",
            "product": "MIS",
            "quantity": 25,
            "average_price": 47850.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200

    queue = client.get("/api/v1/queue/pending")
    assert queue.status_code == 200
    return queue.json()["data"]["pending_entry"][0]["id"]


def _valid_slider_json() -> str:
    return json.dumps(
        {
            "Confidence": 7,
            "Stress": 2,
            "Focus": 8,
            "Market Clarity": 7,
            "Patience": 6,
        }
    )


def test_custom_tag_validation_and_archive_flow(client: TestClient) -> None:
    invalid = client.post("/api/v1/tags/custom", json={"name": "ab"})
    assert invalid.status_code == 422

    created = client.post("/api/v1/tags/custom", json={"name": "gap_play"})
    assert created.status_code in (200, 201)
    tag_id = created.json()["data"]["id"]

    duplicate = client.post("/api/v1/tags/custom", json={"name": "GAP_PLAY"})
    assert duplicate.status_code == 409

    archived = client.delete(f"/api/v1/tags/custom/{tag_id}")
    assert archived.status_code == 200

    # Re-create same normalized name after archive should reactivate.
    recreated = client.post("/api/v1/tags/custom", json={"name": "Gap_Play"})
    assert recreated.status_code in (200, 201)


def test_entry_rejects_exit_only_tags(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Target hit"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "invalid entry tags",
        },
    )
    assert response.status_code == 422


def test_mid_node_not_allowed_while_pending_entry(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "mid",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "invalid state",
        },
    )
    assert response.status_code == 409


def test_slider_validation_missing_dimension(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    broken_sliders = json.dumps(
        {
            "Confidence": 8,
            "Stress": 1,
            "Focus": 8,
            "Patience": 5,
        }
    )

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long", "Breakout", "Range day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": broken_sliders,
            "note": "missing one slider",
        },
    )
    assert response.status_code == 422


def test_attachment_type_validation(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Short", "Pullback", "News driven"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "bad mime",
        },
        files=[("files", ("bad.txt", b"hello", "text/plain"))],
    )
    assert response.status_code == 422


def test_entry_requires_one_tag_from_each_category(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long", "Breakout"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "missing market context",
        },
    )
    assert response.status_code == 422


def test_exit_requires_one_tag_from_each_category(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    entry_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long", "Breakout", "trending day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "valid entry",
        },
    )
    assert entry_response.status_code == 200

    inject_exit = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": "BANKNIFTY24APR-FUT",
            "product": "MIS",
            "average_price": 47890.0,
            "pnl": 1200.0,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert inject_exit.status_code == 200

    exit_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "exit",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Perfect exit", "a+"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "missing outcome",
        },
    )
    assert exit_response.status_code == 422


def test_structured_fixed_tags_payload_is_accepted(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "fixed_tags": json.dumps(
                {
                    "Direction": "Long",
                    "Strategy": "Breakout",
                    "Market context": "trending day",
                }
            ),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "structured tags",
        },
    )

    assert response.status_code == 200
    fixed_tags = response.json()["data"]["node"]["fixed_tags"]
    assert fixed_tags["Direction"] == "Long"
    assert fixed_tags["Strategy"] == "Breakout"
    assert fixed_tags["Market"] == "trending day"


def test_structured_fixed_tags_unknown_category_is_rejected(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "fixed_tags": json.dumps(
                {
                    "Direction": "Long",
                    "Strategy": "Breakout",
                    "Market context": "trending day",
                    "Invalid type": "anything",
                }
            ),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "bad structured tags",
        },
    )

    assert response.status_code == 422
