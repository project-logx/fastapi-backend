from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db
from app.config import settings
from app.database import Base
from app.main import app
from app.services.taxonomy import seed_fixed_taxonomy


@pytest.fixture()
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "test_logx.db"
    attachments_dir = tmp_path / "attachments"

    test_engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False, future=True)

    Base.metadata.create_all(bind=test_engine)

    seed_db = TestingSessionLocal()
    try:
        seed_fixed_taxonomy(seed_db)
        seed_db.commit()
    finally:
        seed_db.close()

    original_attachments_dir = settings.attachments_dir
    settings.attachments_dir = attachments_dir
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    settings.attachments_dir = original_attachments_dir

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture(autouse=True)
def clean_state(client: TestClient) -> None:
    response = client.post("/api/v1/mock/events/reset", params={"keep_tags": "false"})
    assert response.status_code == 200
