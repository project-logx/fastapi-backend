from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.services.behavioral_clustering import run_behavioral_clustering, run_behavioral_clustering_job
from app.services.embeddings import get_or_create_behavioral_profile
from app.services.serialization import serialize_behavioral_profile


router = APIRouter(tags=["behavior"])


@router.post("/behavior/clustering/run")
def trigger_behavioral_clustering(
    background_tasks: BackgroundTasks,
    profile_key: str = "global",
    run_in_background: bool = False,
    min_samples: int = settings.clustering_min_samples,
    max_samples: int = settings.clustering_max_samples,
    db: Session = Depends(get_db),
) -> dict:
    if run_in_background:
        background_tasks.add_task(
            run_behavioral_clustering_job,
            profile_key,
            min_samples,
            max_samples,
        )
        return {
            "data": {
                "status": "scheduled",
                "profile_key": profile_key,
                "min_samples": min_samples,
                "max_samples": max_samples,
            }
        }

    result = run_behavioral_clustering(
        db=db,
        profile_key=profile_key,
        min_samples=min_samples,
        max_samples=max_samples,
    )
    db.commit()
    return {"data": result}


@router.get("/behavior/profile")
def get_behavior_profile(profile_key: str = "global", db: Session = Depends(get_db)) -> dict:
    profile = get_or_create_behavioral_profile(db=db, profile_key=profile_key)
    db.commit()
    db.refresh(profile)
    return {"data": serialize_behavioral_profile(profile)}
