from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models import Attachment, Trade, TradeNode, TradeStatus
from app.services.serialization import serialize_attachment


router = APIRouter(tags=["attachments"])


def _resolve_file_path(file_key: str) -> Path:
    path = settings.attachments_dir / file_key
    return path.resolve()


@router.get("/trades/{trade_id}/nodes/{node_id}/attachments")
def list_node_attachments(trade_id: int, node_id: int, db: Session = Depends(get_db)) -> dict:
    node = (
        db.query(TradeNode)
        .filter(TradeNode.id == node_id, TradeNode.trade_id == trade_id)
        .first()
    )
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    data = [serialize_attachment(item) for item in node.attachments]
    return {"data": data, "meta": {"count": len(data)}}


@router.get("/attachments/{attachment_id}")
def get_attachment(attachment_id: int, db: Session = Depends(get_db)) -> FileResponse:
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_path = _resolve_file_path(attachment.file_key)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment file missing")

    return FileResponse(path=file_path, media_type=attachment.mime_type, filename=attachment.file_name)


@router.delete("/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)) -> dict:
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Attachment not found")

    trade = db.query(Trade).filter(Trade.id == attachment.trade_id).first()
    if trade and trade.status == TradeStatus.COMPLETE.value:
        raise HTTPException(status_code=409, detail="Attachments on completed journeys are immutable")

    file_path = _resolve_file_path(attachment.file_key)
    if file_path.exists():
        file_path.unlink()

    db.delete(attachment)
    db.commit()

    return {"data": {"deleted": True, "id": attachment_id}}
