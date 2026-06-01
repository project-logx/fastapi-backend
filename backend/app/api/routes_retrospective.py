from __future__ import annotations

import json
import logging
import traceback
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models import RetrospectiveReport
from app.services.retrospective import run_retrospective_analysis
from app.services.serialization import serialize_retrospective_report

logger = logging.getLogger(__name__)

router = APIRouter(tags=["behavior"])


@router.get("/debug/llm-test")
def debug_llm_test() -> dict:
    """Diagnostic endpoint: tests .env loading, API key, model, and makes a real OpenAI call."""
    results: dict = {}

    # 1. Check python-dotenv
    try:
        import dotenv
        results["python_dotenv"] = f"installed v{dotenv.__version__}"
    except ImportError:
        results["python_dotenv"] = "NOT INSTALLED"

    # 2. Check settings
    api_key = settings.openai_api_key
    results["openai_api_key_present"] = bool(api_key)
    results["openai_api_key_preview"] = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "(too short or empty)"
    results["openai_base_url"] = settings.openai_base_url
    results["retrospective_llm_model"] = settings.retrospective_llm_model
    results["retrospective_llm_provider"] = settings.retrospective_llm_provider
    results["retrospective_llm_timeout"] = settings.retrospective_llm_timeout_seconds

    # 3. Try a minimal OpenAI API call
    if not api_key:
        results["api_call"] = "SKIPPED: no API key"
        return {"data": results}

    payload = {
        "model": settings.retrospective_llm_model,
        "messages": [{"role": "user", "content": "Say hello in one word."}],
        "temperature": 0.1,
        "max_tokens": 10,
    }
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    results["api_call_url"] = url

    req = urllib_request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            results["api_call"] = "SUCCESS"
            results["api_response"] = content
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        results["api_call"] = f"FAILED: HTTP {exc.code}"
        results["api_error_detail"] = detail
    except Exception as exc:
        results["api_call"] = f"FAILED: {type(exc).__name__}: {exc}"
        results["api_traceback"] = traceback.format_exc()

    return {"data": results}


@router.post("/behavior/retrospective/run")
def run_retrospective(
    days: int = settings.retrospective_default_days,
    profile_key: str = settings.intervention_profile_key,
    include_histories: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    safe_days = max(1, min(days, 90))
    safe_profile_key = (profile_key or "global").strip() or "global"

    logger.info(f"=== /behavior/retrospective/run called: days={safe_days}, profile={safe_profile_key} ===")

    result = run_retrospective_analysis(
        db=db,
        timeframe_days=safe_days,
        profile_key=safe_profile_key,
    )
    db.commit()

    # Log the synthesis result
    report_data = result.get("report", {})
    logger.info(f"  Retrospective result: source={report_data.get('synthesis_source')}, model={report_data.get('synthesis_model')}, trade_count={report_data.get('trade_count')}")

    report_id = report_data.get("id")
    if isinstance(report_id, int):
        persisted = db.query(RetrospectiveReport).filter(RetrospectiveReport.id == report_id).first()
        if persisted is not None:
            result["report"] = serialize_retrospective_report(persisted, include_payload=True)

    if not include_histories:
        retrieval = result.get("retrieval")
        if isinstance(retrieval, dict):
            retrieval.pop("histories", None)

    return {"data": result}


@router.get("/behavior/retrospective/reports")
def list_retrospective_reports(
    profile_key: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> dict:
    safe_limit = max(1, min(limit, 100))
    query = db.query(RetrospectiveReport)
    if profile_key:
        query = query.filter(RetrospectiveReport.profile_key == profile_key.strip())

    rows = query.order_by(desc(RetrospectiveReport.created_at), desc(RetrospectiveReport.id)).limit(safe_limit).all()
    return {
        "data": [serialize_retrospective_report(row, include_payload=False) for row in rows],
        "meta": {"count": len(rows)},
    }


@router.get("/behavior/retrospective/reports/latest")
def latest_retrospective_report(profile_key: str | None = None, db: Session = Depends(get_db)) -> dict:
    query = db.query(RetrospectiveReport)
    if profile_key:
        query = query.filter(RetrospectiveReport.profile_key == profile_key.strip())

    row = query.order_by(desc(RetrospectiveReport.created_at), desc(RetrospectiveReport.id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No retrospective reports found")

    return {"data": serialize_retrospective_report(row, include_payload=True)}


@router.get("/behavior/retrospective/reports/{report_id}")
def retrospective_report_detail(report_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.query(RetrospectiveReport).filter(RetrospectiveReport.id == report_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Retrospective report not found")
    return {"data": serialize_retrospective_report(row, include_payload=True)}
