from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _inject_entry(client: TestClient, symbol: str, qty: int, price: float) -> None:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": symbol,
            "product": "MIS",
            "quantity": qty,
            "average_price": price,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _inject_exit(client: TestClient, symbol: str, price: float, pnl: float) -> None:
    response = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": symbol,
            "product": "MIS",
            "average_price": price,
            "pnl": pnl,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _first_pending_trade_id(client: TestClient, queue_key: str, symbol: str) -> int:
    response = client.get("/api/v1/queue/pending")
    assert response.status_code == 200
    rows = [row for row in response.json()["data"][queue_key] if row["symbol"] == symbol]
    assert rows
    return rows[0]["id"]


def _submit_node(client: TestClient, trade_id: int, node_type: str, fixed_tags: dict[str, str], note: str) -> None:
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": node_type,
            "captured_at": datetime.now(UTC).isoformat(),
            "fixed_tags": json.dumps(fixed_tags),
            "custom_tag_ids": json.dumps([]),
            "sliders": json.dumps(
                {
                    "Confidence": 7,
                    "Stress": 3,
                    "Focus": 8,
                    "Market Clarity": 6,
                    "Patience": 5,
                }
            ),
            "note": note,
        },
    )
    assert response.status_code == 200


def _create_completed_trade(client: TestClient, symbol: str, entry_note: str, mid_note: str, pnl: float, strategy: str) -> None:
    _inject_entry(client, symbol=symbol, qty=10, price=22000.0)
    trade_id = _first_pending_trade_id(client, "pending_entry", symbol)

    _submit_node(
        client,
        trade_id,
        "entry",
        {
            "Direction": "Long",
            "Strategy": strategy,
            "Market": "trending day",
        },
        entry_note,
    )
    _submit_node(
        client,
        trade_id,
        "mid",
        {
            "Direction": "Long",
            "Strategy": strategy,
            "Market": "Range day",
        },
        mid_note,
    )

    _inject_exit(client, symbol=symbol, price=22100.0, pnl=pnl)
    exit_id = _first_pending_trade_id(client, "pending_exit", symbol)
    assert exit_id == trade_id

    _submit_node(
        client,
        trade_id,
        "exit",
        {
            "Execution": "Perfect exit",
            "Quality": "a+",
            "Outcome": "Target hit",
        },
        "closed",
    )


def test_behavior_profile_endpoint_returns_default_profile(client: TestClient) -> None:
    response = client.get("/api/v1/behavior/profile")
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["profile_key"] == "global"
    assert data["sweet_spot_centroid"] == []
    assert data["danger_zone_centroid"] == []


def test_clustering_job_updates_behavior_profile_centroids(client: TestClient) -> None:
    _create_completed_trade(client, "NIFTY24APR-FUT", "high discipline alpha", "stay patient alpha", pnl=1800.0, strategy="Breakout")
    _create_completed_trade(client, "BANKNIFTY24APR-FUT", "high discipline alpha", "stay patient alpha", pnl=1600.0, strategy="Breakout")
    _create_completed_trade(client, "FINNIFTY24APR-FUT", "panic chase beta", "late reaction beta", pnl=-1200.0, strategy="Reversal")
    _create_completed_trade(client, "MIDCPNIFTY24APR-FUT", "panic chase beta", "late reaction beta", pnl=-900.0, strategy="Reversal")

    run_response = client.post(
        "/api/v1/behavior/clustering/run",
        params={"min_samples": 4, "run_in_background": "false"},
    )
    assert run_response.status_code == 200
    result = run_response.json()["data"]

    assert result["status"] == "completed"
    assert result["sample_count"] >= 4
    assert result["cluster_count"] >= 1

    profile_response = client.get("/api/v1/behavior/profile")
    assert profile_response.status_code == 200
    profile = profile_response.json()["data"]

    assert isinstance(profile["sweet_spot_centroid"], list)
    assert isinstance(profile["danger_zone_centroid"], list)
    assert len(profile["sweet_spot_centroid"]) > 0
    assert len(profile["danger_zone_centroid"]) > 0


def test_clustering_returns_skipped_when_samples_insufficient(client: TestClient) -> None:
    _create_completed_trade(client, "NIFTY24APR-FUT", "alpha entry", "alpha mid", pnl=1200.0, strategy="Breakout")

    response = client.post(
        "/api/v1/behavior/clustering/run",
        params={"min_samples": 10, "run_in_background": "false"},
    )
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["status"] == "skipped"
    assert data["reason"] == "insufficient_samples"


def test_clustering_can_be_scheduled_in_background(client: TestClient) -> None:
    response = client.post(
        "/api/v1/behavior/clustering/run",
        params={"run_in_background": "true"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["status"] == "scheduled"
    assert payload["profile_key"] == "global"
