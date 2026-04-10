from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _inject_entry(client: TestClient) -> int:
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

    queue = client.get("/api/v1/queue/pending")
    assert queue.status_code == 200
    return queue.json()["data"]["pending_entry"][0]["id"]


def _sliders() -> str:
    return json.dumps(
        {
            "Confidence": 7,
            "Stress": 3,
            "Focus": 8,
            "Market Clarity": 6,
            "Patience": 5,
        }
    )


def test_node_endpoint_rejects_invalid_json_form_fields(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    bad_tags = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": "not-json",
            "custom_tag_ids": json.dumps([]),
            "sliders": _sliders(),
            "note": "bad tags",
        },
    )
    assert bad_tags.status_code == 422


def test_unknown_custom_tag_ids_are_rejected(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long", "Breakout", "Range day"]),
            "custom_tag_ids": json.dumps([9999]),
            "sliders": _sliders(),
            "note": "bad tag id",
        },
    )
    assert response.status_code == 422


def test_attachment_limit_enforced_at_10_files(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    png = b"\x89PNG\r\n\x1a\n"
    files = [("files", (f"a{i}.png", png, "image/png")) for i in range(11)]

    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Short", "Breakout", "trending day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _sliders(),
            "note": "too many files",
        },
        files=files,
    )
    assert response.status_code == 422


def test_attachment_size_limit_enforced(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    big = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Long", "Pullback", "News driven"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _sliders(),
            "note": "oversized file",
        },
        files=[("files", ("big.png", big, "image/png"))],
    )
    assert response.status_code == 413


def test_duplicate_attachment_payload_is_deduplicated_per_node(client: TestClient) -> None:
    trade_id = _inject_entry(client)

    png_payload = b"\x89PNG\r\n\x1a\n\x00"
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": "entry",
            "captured_at": datetime.now(UTC).isoformat(),
            "tags": json.dumps(["Short", "Price action", "Expiry day"]),
            "custom_tag_ids": json.dumps([]),
            "sliders": _sliders(),
            "note": "dedupe files",
        },
        files=[
            ("files", ("same1.png", png_payload, "image/png")),
            ("files", ("same2.png", png_payload, "image/png")),
        ],
    )
    assert response.status_code == 200
    attachments = response.json()["data"]["node"]["attachments"]
    assert len(attachments) == 1


def test_delete_missing_attachment_returns_404(client: TestClient) -> None:
    response = client.delete("/api/v1/attachments/999999")
    assert response.status_code == 404
