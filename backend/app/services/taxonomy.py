from __future__ import annotations

from sqlalchemy.orm import Session

from app.constants import FIXED_TAXONOMY
from app.models import Tag, TagCategory


def _normalize_name(name: str) -> str:
    return " ".join((name or "").split()).strip().lower()


def seed_fixed_taxonomy(db: Session) -> None:
    for category_name, definition in FIXED_TAXONOMY.items():
        normalized_category = _normalize_name(category_name)
        category = db.query(TagCategory).filter(TagCategory.normalized_name == normalized_category).first()

        if category is None:
            category = TagCategory(
                name=category_name,
                normalized_name=normalized_category,
                category_weight=int(definition["category_weight"]),
            )
            db.add(category)
            db.flush()
        else:
            category.name = category_name
            category.category_weight = int(definition["category_weight"])

        existing_tags = {
            row.normalized_name: row
            for row in db.query(Tag).filter(Tag.category_id == category.id).all()
        }

        for tag_name, tag_score in definition["tags"].items():
            normalized_tag = _normalize_name(tag_name)
            row = existing_tags.get(normalized_tag)
            if row is None:
                row = Tag(
                    category_id=category.id,
                    name=tag_name,
                    normalized_name=normalized_tag,
                    tag_score=int(tag_score),
                )
                db.add(row)
                continue

            row.name = tag_name
            row.tag_score = int(tag_score)
