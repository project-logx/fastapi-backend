from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings:
    app_name = "LogX POC API"
    api_prefix = "/api/v1"
    source_mode = "mock"

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'logx.db').as_posix()}")

    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]

    attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", str(ROOT_DIR / "storage" / "attachments")))


settings = Settings()
