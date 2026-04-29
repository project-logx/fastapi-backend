from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import desc
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.config import settings
from app.constants import ALLOWED_IMAGE_MIME_TYPES, FIXED_TAGS_BY_CATEGORY, MAX_ATTACHMENTS_PER_NODE, MAX_FILE_SIZE_BYTES, NODE_TYPES, SLIDER_DIMENSIONS, TAG_CATEGORIES_BY_NODE_TYPE, normalize_category_name
from app.models import Attachment, CustomTag, TagCategory, Trade, TradeNode, TradeStatus
from app.schemas import TradeUpdateRequest
from app.services.embeddings import EmbeddingPayload, generate_embedding, sync_trade_embeddings_with_final_pnl, upsert_node_embedding_for_trade_node
from app.services.intervention import evaluate_intervention
from app.services.scoring import recompute_trade_quality_score
from app.services.serialization import serialize_node, serialize_node_state_for_embedding, serialize_trade


router = APIRouter(tags=["trades"])


def _json_field(raw: str | None, default: object) -> object:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON form field") from exc


def _parse_time(raw: str | datetime | None) -> datetime:
    if raw is None or raw == "":
        return datetime.now(UTC)

    if isinstance(raw, datetime):
        parsed = raw
    else:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="captured_at must be a valid ISO datetime") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_slider_payload(sliders: object) -> dict[str, int]:
    if not isinstance(sliders, dict):
        raise HTTPException(status_code=422, detail="sliders must be a JSON object")

    normalized: dict[str, int] = {}
    for name in SLIDER_DIMENSIONS:
        if name not in sliders:
            raise HTTPException(status_code=422, detail=f"Missing slider dimension: {name}")
        value = sliders[name]
        if not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail=f"Slider '{name}' must be numeric")
        int_value = int(value)
        if int_value < 0 or int_value > 10:
            raise HTTPException(status_code=422, detail=f"Slider '{name}' must be between 0 and 10")
        normalized[name] = int_value
    return normalized


def _slider_payload_from_scalars(
    confidence: int,
    stress: int,
    focus: int,
    market_clarity: int,
    patience: int,
) -> dict[str, int]:
    return {
        "Confidence": confidence,
        "Stress": stress,
        "Focus": focus,
        "Market Clarity": market_clarity,
        "Patience": patience,
    }


def _taxonomy_for_node_type(db: Session, node_type: str) -> tuple[list[str], dict[str, set[str]], dict[str, str]]:
    categories = TAG_CATEGORIES_BY_NODE_TYPE.get(node_type)
    if categories is None:
        raise HTTPException(status_code=422, detail=f"Unknown node type: {node_type}")

    rows = (
        db.query(TagCategory)
        .options(joinedload(TagCategory.tags))
        .filter(TagCategory.name.in_(categories))
        .all()
    )
    row_by_name = {row.name: row for row in rows}

    allowed_tags_by_category: dict[str, set[str]] = {}
    for category in categories:
        row = row_by_name.get(category)
        if row is None:
            allowed_tags_by_category[category] = set(FIXED_TAGS_BY_CATEGORY.get(category, []))
            continue
        allowed_tags_by_category[category] = {tag.name for tag in row.tags}

    tag_to_category = {
        tag_name: category
        for category, tag_names in allowed_tags_by_category.items()
        for tag_name in tag_names
    }
    return categories, allowed_tags_by_category, tag_to_category


def _validate_fixed_tags(db: Session, node_type: str, fixed_tags: object, tags: object) -> dict[str, str]:
    categories, allowed_tags_by_category, tag_to_category = _taxonomy_for_node_type(db=db, node_type=node_type)

    if fixed_tags is not None:
        if not isinstance(fixed_tags, dict):
            raise HTTPException(status_code=422, detail="fixed_tags must be a JSON object of category -> tag")

        normalized_input: dict[str, str] = {}
        alias_collisions: list[str] = []
        for raw_category, raw_value in fixed_tags.items():
            canonical_category = normalize_category_name(str(raw_category))
            if canonical_category in normalized_input:
                alias_collisions.append(str(raw_category))
                continue
            normalized_input[canonical_category] = raw_value

        if alias_collisions:
            raise HTTPException(status_code=422, detail=f"Duplicate category aliases detected: {alias_collisions}")

        unknown_categories = [category for category in normalized_input if category not in categories]
        if unknown_categories:
            raise HTTPException(status_code=422, detail=f"Unknown fixed tag category(ies): {unknown_categories}")

        selected_by_category: dict[str, str] = {}
        missing_categories: list[str] = []

        for category in categories:
            value = normalized_input.get(category)
            if not isinstance(value, str) or not value.strip():
                missing_categories.append(category)
                continue

            normalized = value.strip()
            if normalized not in allowed_tags_by_category.get(category, set()):
                raise HTTPException(status_code=422, detail=f"Tag '{normalized}' not allowed for category '{category}'")
            selected_by_category[category] = normalized

        if missing_categories:
            raise HTTPException(status_code=422, detail=f"Missing required tag category selection(s): {missing_categories}")

        return selected_by_category

    if not isinstance(tags, list):
        raise HTTPException(status_code=422, detail="tags must be a JSON array")

    values = [str(item).strip() for item in tags if str(item).strip()]

    unknown = [value for value in values if value not in tag_to_category]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Tag(s) not allowed for {node_type}: {unknown}")

    selected_by_category = {}
    for value in values:
        category = tag_to_category[value]
        if category in selected_by_category:
            raise HTTPException(status_code=422, detail=f"Select exactly one tag for category '{category}'")
        selected_by_category[category] = value

    missing_categories = [category for category in categories if category not in selected_by_category]
    if missing_categories:
        raise HTTPException(status_code=422, detail=f"Missing required tag category selection(s): {missing_categories}")

    return {category: selected_by_category[category] for category in categories}


def _load_custom_tags(db: Session, ids: object) -> list[CustomTag]:
    if not isinstance(ids, list):
        raise HTTPException(status_code=422, detail="custom_tag_ids must be a JSON array")
    parsed_ids = []
    for item in ids:
        try:
            parsed_ids.append(int(item))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="custom_tag_ids must contain integers") from exc

    if not parsed_ids:
        return []

    rows = (
        db.query(CustomTag)
        .filter(CustomTag.id.in_(parsed_ids), CustomTag.archived_at.is_(None))
        .all()
    )
    found = {row.id for row in rows}
    missing = [value for value in parsed_ids if value not in found]
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown or archived custom_tag_ids: {missing}")
    return rows


def _validate_node_state(trade: Trade, node_type: str) -> None:
    if node_type == "entry" and trade.status != TradeStatus.PENDING_ENTRY.value:
        raise HTTPException(status_code=409, detail="Entry node allowed only when trade is pending_entry")
    if node_type == "mid" and trade.status != TradeStatus.ACTIVE.value:
        raise HTTPException(status_code=409, detail="Mid node allowed only when trade is active")
    if node_type == "exit" and trade.status != TradeStatus.PENDING_EXIT.value:
        raise HTTPException(status_code=409, detail="Exit node allowed only when trade is pending_exit")


async def _submit_trade_node_internal(
    trade_id: int,
    node_type: str,
    captured_at: str | datetime | None,
    fixed_tags_payload: object,
    tags_payload: object,
    custom_tag_ids_payload: object,
    sliders_payload: object,
    note: str | None,
    files: list[UploadFile] | None,
    confirm_intervention: bool,
    db: Session,
) -> dict:
    if node_type not in NODE_TYPES:
        raise HTTPException(status_code=422, detail=f"type must be one of: {', '.join(NODE_TYPES)}")

    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    _validate_node_state(trade, node_type)

    normalized_fixed_tags = _validate_fixed_tags(db=db, node_type=node_type, fixed_tags=fixed_tags_payload, tags=tags_payload)
    linked_custom_tags = _load_custom_tags(db, custom_tag_ids_payload)
    normalized_sliders = _normalize_slider_payload(sliders_payload)
    node_time = _parse_time(captured_at)

    serialized_state: str | None = None
    embedding_payload: EmbeddingPayload | None = None
    if node_type in {"entry", "mid"}:
        serialized_state = serialize_node_state_for_embedding(
            node_type=node_type,
            sliders=normalized_sliders,
            fixed_tags=normalized_fixed_tags,
            note=(note or "").strip(),
        )
        embedding_payload = generate_embedding(serialized_state)

        if not confirm_intervention:
            intervention = evaluate_intervention(
                db=db,
                trade=trade,
                node_type=node_type,
                current_vector=embedding_payload.vector,
                sliders=normalized_sliders,
                note=(note or "").strip(),
            )
            if intervention:
                return {
                    "data": {
                        "status": "intervention_required",
                        "requires_confirmation": True,
                        "intervention": intervention,
                        "trade": serialize_trade(trade, include_nodes=False),
                    }
                }

    node = TradeNode(
        trade_id=trade.id,
        node_type=node_type,
        captured_at=node_time,
        fixed_tags=normalized_fixed_tags,
        sliders=normalized_sliders,
        note=(note or "").strip(),
        is_locked=True,
    )
    db.add(node)
    db.flush()

    for tag in linked_custom_tags:
        node.custom_tags.append(tag)

    uploaded_files = files or []
    if len(uploaded_files) > MAX_ATTACHMENTS_PER_NODE:
        raise HTTPException(status_code=422, detail=f"At most {MAX_ATTACHMENTS_PER_NODE} attachments allowed per node")

    # Session autoflush is disabled, so keep an in-request checksum set to avoid duplicate binary uploads.
    existing_checksums = {
        row[0]
        for row in db.query(Attachment.checksum_sha256)
        .filter(Attachment.node_id == node.id)
        .all()
    }

    for upload in uploaded_files:
        content_type = upload.content_type or ""
        if content_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type}")

        content = await upload.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"File '{upload.filename}' exceeds max allowed size")

        checksum = hashlib.sha256(content).hexdigest()
        if checksum in existing_checksums:
            continue
        existing_checksums.add(checksum)

        safe_name = Path(upload.filename or "attachment").name
        generated_name = f"{uuid4().hex}_{safe_name}"

        relative_path = Path(f"trade_{trade.id}") / f"node_{node.id}" / generated_name
        absolute_path = settings.attachments_dir / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(content)

        row = Attachment(
            trade_id=trade.id,
            node_id=node.id,
            file_name=safe_name,
            file_key=relative_path.as_posix(),
            mime_type=content_type,
            size_bytes=len(content),
            caption=None,
            captured_at=node_time,
            checksum_sha256=checksum,
        )
        db.add(row)

    if node_type in {"entry", "mid"}:
        if not serialized_state or embedding_payload is None:
            raise HTTPException(status_code=500, detail="Embedding payload was not prepared")
        upsert_node_embedding_for_trade_node(
            db=db,
            trade=trade,
            node=node,
            serialized_state=serialized_state,
            embedding_payload=embedding_payload,
        )

    if node_type == "entry":
        trade.status = TradeStatus.ACTIVE.value
    elif node_type == "exit":
        trade.status = TradeStatus.COMPLETE.value
        if not trade.closed_at:
            trade.closed_at = node_time
        sync_trade_embeddings_with_final_pnl(db=db, trade_id=trade.id, pnl=trade.pnl)

    try:
        recompute_trade_quality_score(db=db, trade=trade)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    db.refresh(node)
    db.refresh(trade)

    return {
        "data": {
            "node": serialize_node(node),
            "trade": serialize_trade(trade, include_nodes=False),
        }
    }


@router.get("/queue/pending")
def queue_pending(symbol: str | None = None, limit: int = 100, db: Session = Depends(get_db)) -> dict:
    safe_limit = max(1, min(limit, 500))

    query = db.query(Trade).filter(Trade.status.in_([TradeStatus.PENDING_ENTRY.value, TradeStatus.PENDING_EXIT.value]))
    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())

    rows = query.order_by(desc(Trade.updated_at), desc(Trade.id)).limit(safe_limit).all()

    now = datetime.now(UTC)
    pending_entry = []
    pending_exit = []

    for trade in rows:
        item = serialize_trade(trade, include_nodes=False)
        anchor = trade.closed_at if trade.status == TradeStatus.PENDING_EXIT.value and trade.closed_at else trade.opened_at
        if anchor:
            item["waiting_seconds"] = int((now - anchor.astimezone(UTC)).total_seconds())
        else:
            item["waiting_seconds"] = None

        if trade.status == TradeStatus.PENDING_ENTRY.value:
            pending_entry.append(item)
        else:
            pending_exit.append(item)

    return {
        "data": {
            "pending_entry": pending_entry,
            "pending_exit": pending_exit,
        },
        "meta": {
            "count": len(rows),
        },
    }


@router.get("/trades/active")
def active_trades(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(Trade)
        .filter(Trade.status == TradeStatus.ACTIVE.value)
        .order_by(desc(Trade.updated_at), desc(Trade.id))
        .all()
    )
    return {"data": [serialize_trade(item) for item in rows], "meta": {"count": len(rows)}}


@router.get("/trades/{trade_id}")
def trade_detail(trade_id: int, db: Session = Depends(get_db)) -> dict:
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return {"data": serialize_trade(trade, include_nodes=True)}


@router.put("/trades/{trade_id}")
def update_trade_tags(trade_id: int, payload: TradeUpdateRequest, db: Session = Depends(get_db)) -> dict:
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    node_by_id = {node.id: node for node in trade.nodes}
    for node_update in payload.node_updates:
        node = node_by_id.get(node_update.node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"Trade node {node_update.node_id} not found for trade {trade_id}")

        fixed_tags_changed = node_update.fixed_tags is not None
        note_changed = node_update.note is not None

        if fixed_tags_changed:
            node.fixed_tags = _validate_fixed_tags(db=db, node_type=node.node_type, fixed_tags=node_update.fixed_tags, tags=[])

        if node_update.custom_tag_ids is not None:
            node.custom_tags = _load_custom_tags(db, node_update.custom_tag_ids)

        if note_changed:
            node.note = (node_update.note or "").strip()

        if node.node_type in {"entry", "mid"} and (fixed_tags_changed or note_changed):
            serialized_state = serialize_node_state_for_embedding(
                node_type=node.node_type,
                sliders=node.sliders,
                fixed_tags=node.fixed_tags,
                note=node.note,
            )
            upsert_node_embedding_for_trade_node(
                db=db,
                trade=trade,
                node=node,
                serialized_state=serialized_state,
            )

    try:
        recompute_trade_quality_score(db=db, trade=trade)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if trade.status == TradeStatus.COMPLETE.value:
        sync_trade_embeddings_with_final_pnl(db=db, trade_id=trade.id, pnl=trade.pnl)

    db.commit()
    db.refresh(trade)
    return {"data": serialize_trade(trade, include_nodes=True)}


@router.post("/trades/{trade_id}/nodes")
async def submit_trade_node(
    trade_id: int,
    type: str = Form(...),
    captured_at: str | None = Form(default=None),
    fixed_tags: str | None = Form(default=None),
    tags: str | None = Form(default="[]"),
    custom_tag_ids: str | None = Form(default="[]"),
    sliders: str | None = Form(default="{}"),
    note: str | None = Form(default=""),
    confirm_intervention: bool = Form(default=False),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    node_type = type.strip().lower()
    parsed_fixed_tags = _json_field(fixed_tags, None)
    parsed_tags = _json_field(tags, [])
    parsed_custom_ids = _json_field(custom_tag_ids, [])
    parsed_sliders = _json_field(sliders, {})
    return await _submit_trade_node_internal(
        trade_id=trade_id,
        node_type=node_type,
        captured_at=captured_at,
        fixed_tags_payload=parsed_fixed_tags,
        tags_payload=parsed_tags,
        custom_tag_ids_payload=parsed_custom_ids,
        sliders_payload=parsed_sliders,
        note=note,
        files=files,
        confirm_intervention=confirm_intervention,
        db=db,
    )


@router.post("/trades/{trade_id}/nodes/entry", summary="Capture Entry Node (Docs-Friendly)")
async def submit_entry_node_docs(
    trade_id: int,
    direction: str = Form(...),
    strategy: str = Form(...),
    market_context: str = Form(...),
    confidence: int = Form(5, ge=0, le=10),
    stress: int = Form(5, ge=0, le=10),
    focus: int = Form(5, ge=0, le=10),
    market_clarity: int = Form(5, ge=0, le=10),
    patience: int = Form(5, ge=0, le=10),
    note: str | None = Form(default=""),
    captured_at: datetime | None = Form(default=None),
    confirm_intervention: bool = Form(default=False),
    custom_tag_ids: list[int] | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    fixed_tags_payload = {
        "Direction": direction.strip(),
        "Strategy": strategy.strip(),
        "Market": market_context.strip(),
    }
    sliders_payload = _slider_payload_from_scalars(confidence, stress, focus, market_clarity, patience)
    return await _submit_trade_node_internal(
        trade_id=trade_id,
        node_type="entry",
        captured_at=captured_at,
        fixed_tags_payload=fixed_tags_payload,
        tags_payload=[],
        custom_tag_ids_payload=custom_tag_ids or [],
        sliders_payload=sliders_payload,
        note=note,
        files=files,
        confirm_intervention=confirm_intervention,
        db=db,
    )


@router.post("/trades/{trade_id}/nodes/mid", summary="Capture Mid Node (Docs-Friendly)")
async def submit_mid_node_docs(
    trade_id: int,
    direction: str = Form(...),
    strategy: str = Form(...),
    market_context: str = Form(...),
    confidence: int = Form(5, ge=0, le=10),
    stress: int = Form(5, ge=0, le=10),
    focus: int = Form(5, ge=0, le=10),
    market_clarity: int = Form(5, ge=0, le=10),
    patience: int = Form(5, ge=0, le=10),
    note: str | None = Form(default=""),
    captured_at: datetime | None = Form(default=None),
    confirm_intervention: bool = Form(default=False),
    custom_tag_ids: list[int] | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    fixed_tags_payload = {
        "Direction": direction.strip(),
        "Strategy": strategy.strip(),
        "Market": market_context.strip(),
    }
    sliders_payload = _slider_payload_from_scalars(confidence, stress, focus, market_clarity, patience)
    return await _submit_trade_node_internal(
        trade_id=trade_id,
        node_type="mid",
        captured_at=captured_at,
        fixed_tags_payload=fixed_tags_payload,
        tags_payload=[],
        custom_tag_ids_payload=custom_tag_ids or [],
        sliders_payload=sliders_payload,
        note=note,
        files=files,
        confirm_intervention=confirm_intervention,
        db=db,
    )


@router.post("/trades/{trade_id}/nodes/exit", summary="Capture Exit Node (Docs-Friendly)")
async def submit_exit_node_docs(
    trade_id: int,
    execution: str = Form(...),
    result_quality: str = Form(...),
    outcome: str = Form(...),
    confidence: int = Form(5, ge=0, le=10),
    stress: int = Form(5, ge=0, le=10),
    focus: int = Form(5, ge=0, le=10),
    market_clarity: int = Form(5, ge=0, le=10),
    patience: int = Form(5, ge=0, le=10),
    note: str | None = Form(default=""),
    captured_at: datetime | None = Form(default=None),
    confirm_intervention: bool = Form(default=False),
    custom_tag_ids: list[int] | None = Form(default=None),
    files: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> dict:
    fixed_tags_payload = {
        "Execution": execution.strip(),
        "Quality": result_quality.strip(),
        "Outcome": outcome.strip(),
    }
    sliders_payload = _slider_payload_from_scalars(confidence, stress, focus, market_clarity, patience)
    return await _submit_trade_node_internal(
        trade_id=trade_id,
        node_type="exit",
        captured_at=captured_at,
        fixed_tags_payload=fixed_tags_payload,
        tags_payload=[],
        custom_tag_ids_payload=custom_tag_ids or [],
        sliders_payload=sliders_payload,
        note=note,
        files=files,
        confirm_intervention=confirm_intervention,
        db=db,
    )
