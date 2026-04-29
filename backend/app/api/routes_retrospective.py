from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models import RetrospectiveReport
from app.services.retrospective import run_retrospective_analysis
from app.services.serialization import serialize_retrospective_report


router = APIRouter(tags=["behavior"])


@router.post("/behavior/retrospective/run")
def run_retrospective(
    days: int = settings.retrospective_default_days,
    profile_key: str = settings.intervention_profile_key,
    include_histories: bool = False,
    db: Session = Depends(get_db),
) -> dict:
    safe_days = max(1, min(days, 90))
    safe_profile_key = (profile_key or "global").strip() or "global"

    result = run_retrospective_analysis(
        db=db,
        timeframe_days=safe_days,
        profile_key=safe_profile_key,
    )
    db.commit()

    report_id = result.get("report", {}).get("id")
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
