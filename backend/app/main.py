from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_attachments import router as attachments_router
from app.api.routes_health import router as health_router
from app.api.routes_journeys import router as journeys_router
from app.api.routes_metadata import router as metadata_router
from app.api.routes_mock import router as mock_router
from app.api.routes_tags import router as tags_router
from app.api.routes_trades import router as trades_router
from app.config import settings
from app.database import Base, engine


app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(metadata_router, prefix=settings.api_prefix)
app.include_router(mock_router, prefix=settings.api_prefix)
app.include_router(tags_router, prefix=settings.api_prefix)
app.include_router(trades_router, prefix=settings.api_prefix)
app.include_router(journeys_router, prefix=settings.api_prefix)
app.include_router(attachments_router, prefix=settings.api_prefix)
