from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import CustomTag
from app.schemas import CustomTagCreate, CustomTagUpdate
from app.services.serialization import serialize_custom_tag


TAG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,50}$")

router = APIRouter(tags=["tags"])


def _normalize_name(name: str) -> str:
    normalized = name.strip().lower()
    if not TAG_PATTERN.fullmatch(name.strip()):
        raise HTTPException(status_code=422, detail="Tag name must be 3-50 chars and contain only letters, numbers, underscore, or hyphen")
    if normalized.startswith("_system_") or normalized.startswith("_fixed_"):
        raise HTTPException(status_code=422, detail="Tag name uses a reserved prefix")
    return normalized


@router.post("/tags/custom")
def create_custom_tag(payload: CustomTagCreate, db: Session = Depends(get_db)) -> dict:
    normalized_name = _normalize_name(payload.name)

    existing = db.query(CustomTag).filter(CustomTag.normalized_name == normalized_name).first()
    if existing and existing.archived_at is None:
        raise HTTPException(status_code=409, detail="Custom tag already exists")

    if existing and existing.archived_at is not None:
        existing.archived_at = None
        existing.name = payload.name.strip()
        existing.category = payload.category
        db.commit()
        db.refresh(existing)
        return {"data": serialize_custom_tag(existing)}

    tag = CustomTag(
        name=payload.name.strip(),
        normalized_name=normalized_name,
        category=payload.category,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {"data": serialize_custom_tag(tag)}


@router.get("/tags/custom")
def list_custom_tags(include_archived: bool = False, db: Session = Depends(get_db)) -> dict:
    query = db.query(CustomTag)
    if not include_archived:
        query = query.filter(CustomTag.archived_at.is_(None))

    tags = query.order_by(CustomTag.name.asc()).all()
    return {"data": [serialize_custom_tag(tag) for tag in tags], "meta": {"total": len(tags)}}


@router.patch("/tags/custom/{tag_id}")
def update_custom_tag(tag_id: int, payload: CustomTagUpdate, db: Session = Depends(get_db)) -> dict:
    tag = db.query(CustomTag).filter(CustomTag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Custom tag not found")

    if payload.name is not None:
        normalized_name = _normalize_name(payload.name)
        existing = db.query(CustomTag).filter(CustomTag.normalized_name == normalized_name, CustomTag.id != tag.id).first()
        if existing and existing.archived_at is None:
            raise HTTPException(status_code=409, detail="Custom tag already exists")
        tag.name = payload.name.strip()
        tag.normalized_name = normalized_name

    if payload.category is not None:
        tag.category = payload.category

    db.commit()
    db.refresh(tag)
    return {"data": serialize_custom_tag(tag)}


@router.delete("/tags/custom/{tag_id}")
def archive_custom_tag(tag_id: int, db: Session = Depends(get_db)) -> dict:
    tag = db.query(CustomTag).filter(CustomTag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Custom tag not found")

    if tag.archived_at is None:
        tag.archived_at = datetime.now(UTC)
        db.commit()

    return {"data": {"id": tag.id, "archived": True}}
