from __future__ import annotations

from fastapi import APIRouter

from app.config import settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "data": {
            "status": "ok",
            "app": settings.app_name,
        },
        "meta": {
            "source_mode": settings.source_mode,
        },
    }


@router.get("/integration/source-mode")
def source_mode() -> dict:
    return {
        "data": {
            "mode": settings.source_mode,
            "external_api_calls": False,
        }
    }
