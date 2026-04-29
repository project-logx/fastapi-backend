from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient


def _inject_entry(client: TestClient, symbol: str, quantity: int, average_price: float) -> None:
    response = client.post(
        "/api/v1/mock/events/entry",
        json={
            "symbol": symbol,
            "product": "MIS",
            "quantity": quantity,
            "average_price": average_price,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200


def _inject_exit(client: TestClient, symbol: str, average_price: float, pnl: float) -> None:
    response = client.post(
        "/api/v1/mock/events/exit",
        json={
            "symbol": symbol,
            "product": "MIS",
            "average_price": average_price,
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


def _submit_node(
    client: TestClient,
    trade_id: int,
    node_type: str,
    fixed_tags: dict[str, str],
    note: str,
    confidence: int,
    stress: int,
) -> None:
    response = client.post(
        f"/api/v1/trades/{trade_id}/nodes",
        data={
            "type": node_type,
            "captured_at": datetime.now(UTC).isoformat(),
            "fixed_tags": json.dumps(fixed_tags),
            "custom_tag_ids": json.dumps([]),
            "sliders": json.dumps(
                {
                    "Confidence": confidence,
                    "Stress": stress,
                    "Focus": 7,
                    "Market Clarity": 6,
                    "Patience": 5,
                }
            ),
            "note": note,
            "confirm_intervention": "true",
        },
    )
    assert response.status_code == 200


def _create_completed_trade(
    client: TestClient,
    symbol: str,
    pnl: float,
    strategy: str,
    confidence: int,
    stress: int,
) -> None:
    _inject_entry(client, symbol=symbol, quantity=20, average_price=22100.0)
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
        note=f"entry-{symbol}",
        confidence=confidence,
        stress=stress,
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
        note=f"mid-{symbol}",
        confidence=max(1, confidence - 1),
        stress=min(10, stress + 1),
    )

    _inject_exit(client, symbol=symbol, average_price=22130.0, pnl=pnl)
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
        note=f"exit-{symbol}",
        confidence=max(1, confidence - 2),
        stress=min(10, stress + 2),
    )


def test_retrospective_run_generates_report_with_retrieval_and_metrics(client: TestClient) -> None:
    _create_completed_trade(client, "NIFTY24APR-FUT", pnl=1500.0, strategy="Breakout", confidence=8, stress=3)
    _create_completed_trade(client, "BANKNIFTY24APR-FUT", pnl=900.0, strategy="Pullback", confidence=7, stress=4)
    _create_completed_trade(client, "FINNIFTY24APR-FUT", pnl=-700.0, strategy="Reversal", confidence=4, stress=8)

    response = client.post(
        "/api/v1/behavior/retrospective/run",
        params={"days": 30, "profile_key": "global", "include_histories": "true"},
    )
    assert response.status_code == 200

    data = response.json()["data"]
    report = data["report"]
    retrieval = data["retrieval"]

    assert report["id"] > 0
    assert report["trade_count"] >= 3
    assert isinstance(report["report_markdown"], str)
    assert report["report_markdown"].strip()

    assert retrieval["trade_count"] >= 3
    assert retrieval["timeframe_days"] == 30
    assert isinstance(retrieval["histories"], list)
    assert len(retrieval["histories"]) >= 3

    feature_importance = data["feature_importance"]
    assert feature_importance["source"] in {"xgboost_shap", "proxy_correlation"}
    assert isinstance(feature_importance["details"], list)

    assert report["synthesis_source"] in {"fallback", "openai", "azure_openai"}


def test_retrospective_reports_list_latest_and_detail_endpoints(client: TestClient) -> None:
    _create_completed_trade(client, "MIDCPNIFTY24APR-FUT", pnl=1200.0, strategy="Breakout", confidence=7, stress=5)

    run_response = client.post(
        "/api/v1/behavior/retrospective/run",
        params={"days": 14, "profile_key": "global", "include_histories": "false"},
    )
    assert run_response.status_code == 200
    report_id = run_response.json()["data"]["report"]["id"]

    list_response = client.get("/api/v1/behavior/retrospective/reports", params={"limit": 10})
    assert list_response.status_code == 200
    rows = list_response.json()["data"]
    assert rows
    assert any(row["id"] == report_id for row in rows)

    latest_response = client.get("/api/v1/behavior/retrospective/reports/latest")
    assert latest_response.status_code == 200
    latest = latest_response.json()["data"]
    assert latest["id"] == report_id
    assert isinstance(latest["report_markdown"], str)

    detail_response = client.get(f"/api/v1/behavior/retrospective/reports/{report_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["id"] == report_id
    assert isinstance(detail["retrieval_summary"], dict)
    assert isinstance(detail["feature_metrics"], dict)
    assert isinstance(detail["drift_metrics"], dict)


def test_retrospective_run_handles_empty_timeframe(client: TestClient) -> None:
    response = client.post(
        "/api/v1/behavior/retrospective/run",
        params={"days": 7, "profile_key": "global", "include_histories": "false"},
    )
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["retrieval"]["trade_count"] == 0
    assert data["report"]["trade_count"] == 0
    assert isinstance(data["report"]["report_markdown"], str)
    assert data["report"]["report_markdown"].strip()
