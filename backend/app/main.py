from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("backend.log", mode="a")
    ]
)
logger = logging.getLogger(__name__)

from app.api.routes_admin import router as admin_router
from app.api.routes_attachments import router as attachments_router
from app.api.routes_behavior import router as behavior_router
from app.api.routes_health import router as health_router
from app.api.routes_journeys import router as journeys_router
from app.api.routes_metadata import router as metadata_router
from app.api.routes_mock import router as mock_router
from app.api.routes_retrospective import router as retrospective_router
from app.api.routes_tags import router as tags_router
from app.api.routes_trades import router as trades_router
from app.api.routes_auth import router as auth_router
from app.api.routes_kite_connect import router as kite_connect_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.schema_migrations import apply_lightweight_migrations
from app.services.taxonomy import seed_fixed_taxonomy


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    apply_lightweight_migrations(engine)
    db = SessionLocal()
    try:
        seed_fixed_taxonomy(db)
        db.commit()
    finally:
        db.close()
    yield
    # Shutdown (no cleanup needed currently)


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    same_site="lax",
)

app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(metadata_router, prefix=settings.api_prefix)
app.include_router(mock_router, prefix=settings.api_prefix)
app.include_router(tags_router, prefix=settings.api_prefix)
app.include_router(trades_router, prefix=settings.api_prefix)
app.include_router(journeys_router, prefix=settings.api_prefix)
app.include_router(attachments_router, prefix=settings.api_prefix)
app.include_router(behavior_router, prefix=settings.api_prefix)
app.include_router(retrospective_router, prefix=settings.api_prefix)
app.include_router(admin_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(kite_connect_router, prefix=settings.api_prefix)
