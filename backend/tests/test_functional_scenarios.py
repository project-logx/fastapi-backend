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


def _inject_entry(client: TestClient, symbol: str, quantity: int = 50, event_id: str | None = None) -> None:
    payload = {
        "symbol": symbol,
        "product": "MIS",
        "quantity": quantity,
        "average_price": 22000.0,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if event_id:
        payload["event_id"] = event_id
    response = client.post("/api/v1/mock/events/entry", json=payload)
    assert response.status_code == 200


def _inject_exit(client: TestClient, symbol: str, pnl: float = 1000.0, event_id: str | None = None) -> None:
    payload = {
        "symbol": symbol,
        "product": "MIS",
        "average_price": 22020.0,
        "pnl": pnl,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if event_id:
        payload["event_id"] = event_id
    response = client.post("/api/v1/mock/events/exit", json=payload)
    assert response.status_code == 200


def _first_pending_trade_id(client: TestClient, side: str) -> int:
    queue = client.get("/api/v1/queue/pending")
    assert queue.status_code == 200
    rows = queue.json()["data"][side]
    assert rows
    return rows[0]["id"]


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


def _submit_entry(client: TestClient, trade_id: int, tags: list[str] | None = None) -> None:
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(tags or ["Long", "Breakout", "trending day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "entry note",
        },
        files=[("files", ("entry.png", PNG_BYTES, "image/png"))],
    )
    assert response.status_code == 200


def _submit_exit(client: TestClient, trade_id: int) -> None:
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "exit",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Perfect exit", "a+", "Target hit"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "exit note",
        },
        files=[("files", ("exit.png", PNG_BYTES, "image/png"))],
    )
    assert response.status_code == 200


def test_source_mode_contract(client: TestClient) -> None:
    response = client.get("/api/v1/integration/source-mode")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["mode"] == "mock"
    assert body["external_api_calls"] is False


def test_queue_filter_and_limit_contract(client: TestClient) -> None:
    _inject_entry(client, "NIFTY24APR-FUT", event_id="qf-1")
    _inject_entry(client, "BANKNIFTY24APR-FUT", event_id="qf-2")

    filtered = client.get("/api/v1/queue/pending", params={"symbol": "NIFTY24APR-FUT"})
    assert filtered.status_code == 200
    rows = filtered.json()["data"]["pending_entry"]
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NIFTY24APR-FUT"

    limit_floor = client.get("/api/v1/queue/pending", params={"limit": 0})
    assert limit_floor.status_code == 200
    total_rows = len(limit_floor.json()["data"]["pending_entry"]) + len(limit_floor.json()["data"]["pending_exit"])
    assert total_rows == 1


def test_batch_events_and_history_limit(client: TestClient) -> None:
    payload = {
        "events": [
            {
                "event_id": "batch-1",
                "event_type": "entry",
                "timestamp": datetime.now(UTC).isoformat(),
                "positions": [
                    {
                        "tradingsymbol": "NIFTY24APR-FUT",
                        "product": "MIS",
                        "net_quantity": 20,
                        "average_price": 22010.0,
                        "pnl": 0,
                    }
                ],
            },
            {
                "event_id": "batch-2",
                "event_type": "entry",
                "timestamp": datetime.now(UTC).isoformat(),
                "positions": [
                    {
                        "tradingsymbol": "BANKNIFTY24APR-FUT",
                        "product": "MIS",
                        "net_quantity": 10,
                        "average_price": 48100.0,
                        "pnl": 0,
                    }
                ],
            },
            {
                "event_id": "batch-3",
                "event_type": "exit",
                "timestamp": datetime.now(UTC).isoformat(),
                "positions": [
                    {
                        "tradingsymbol": "NIFTY24APR-FUT",
                        "product": "MIS",
                        "net_quantity": 0,
                        "average_price": 22015.0,
                        "pnl": 200.0,
                    }
                ],
            },
        ]
    }

    response = client.post("/api/v1/mock/events/batch", json=payload)
    assert response.status_code == 200
    assert response.json()["meta"]["count"] == 3

    history = client.get("/api/v1/mock/events/history", params={"limit": 2})
    assert history.status_code == 200
    assert history.json()["meta"]["count"] == 2


def test_flip_transition_creates_pending_exit_and_new_pending_entry(client: TestClient) -> None:
    _inject_entry(client, "NIFTY24APR-FUT", quantity=30, event_id="flip-start")

    flip_event = {
        "events": [
            {
                "event_id": "flip-evt",
                "event_type": "flip",
                "timestamp": datetime.now(UTC).isoformat(),
                "positions": [
                    {
                        "tradingsymbol": "NIFTY24APR-FUT",
                        "product": "MIS",
                        "net_quantity": -15,
                        "average_price": 21990.0,
                        "pnl": -300.0,
                    }
                ],
            }
        ]
    }

    response = client.post("/api/v1/mock/events/batch", json=flip_event)
    assert response.status_code == 200

    queue = client.get("/api/v1/queue/pending")
    assert queue.status_code == 200
    pending_entry = [x for x in queue.json()["data"]["pending_entry"] if x["symbol"] == "NIFTY24APR-FUT"]
    pending_exit = [x for x in queue.json()["data"]["pending_exit"] if x["symbol"] == "NIFTY24APR-FUT"]

    assert len(pending_entry) == 1
    assert len(pending_exit) == 1


def test_journey_endpoint_for_incomplete_trade_returns_409(client: TestClient) -> None:
    _inject_entry(client, "NIFTY24APR-FUT")
    trade_id = _first_pending_trade_id(client, "pending_entry")

    response = client.get(f"/api/v1/journeys/{trade_id}")
    assert response.status_code == 409


def test_reset_keep_tags_true_preserves_tag_rows(client: TestClient) -> None:
    tag = client.post("/api/v1/tags/custom", json={"name": "preserve_me"})
    assert tag.status_code in (200, 201)

    reset = client.post("/api/v1/mock/events/reset", params={"keep_tags": "true"})
    assert reset.status_code == 200

    tags_after = client.get("/api/v1/tags/custom")
    assert tags_after.status_code == 200
    names = [item["name"] for item in tags_after.json()["data"]]
    assert "preserve_me" in names


def test_include_archived_custom_tags_query(client: TestClient) -> None:
    created = client.post("/api/v1/tags/custom", json={"name": "archive_test"})
    assert created.status_code in (200, 201)
    tag_id = created.json()["data"]["id"]

    archived = client.delete(f"/api/v1/tags/custom/{tag_id}")
    assert archived.status_code == 200

    active_only = client.get("/api/v1/tags/custom")
    assert active_only.status_code == 200
    assert active_only.json()["meta"]["total"] == 0

    with_archived = client.get("/api/v1/tags/custom", params={"include_archived": "true"})
    assert with_archived.status_code == 200
    assert with_archived.json()["meta"]["total"] == 1
    assert with_archived.json()["data"][0]["archived_at"] is not None


def test_replay_contract_includes_nodes_in_chronological_order(client: TestClient) -> None:
    _inject_entry(client, "NIFTY24APR-FUT", event_id="rep-entry")
    trade_id = _first_pending_trade_id(client, "pending_entry")
    _submit_entry(client, trade_id)

    mid_response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "mid",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Short", "Reversal", "Range day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _valid_slider_json(),
            "note": "mid note",
        },
    )
    assert mid_response.status_code == 200

    _inject_exit(client, "NIFTY24APR-FUT", event_id="rep-exit")
    _submit_exit(client, trade_id)

    journeys = client.get("/api/v1/journeys")
    assert journeys.status_code == 200
    assert journeys.json()["meta"]["count"] == 1

    journey_id = journeys.json()["data"][0]["id"]
    replay = client.get(f"/api/v1/journeys/{journey_id}")
    assert replay.status_code == 200

    nodes = replay.json()["data"]["nodes"]
    assert [node["type"] for node in nodes] == ["entry", "mid", "exit"]
