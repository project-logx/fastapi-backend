from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if python-dotenv is installed.
# This allows users to place secrets in backend/.env instead of
# exporting shell variables before every server start.
_dotenv_loaded = False
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parents[1] / ".env"
    _dotenv_loaded = load_dotenv(dotenv_path=_env_path, override=True)
    print(f"[CONFIG] dotenv: loaded={_dotenv_loaded}, path={_env_path}, exists={_env_path.exists()}")
except ImportError:  # pragma: no cover – python-dotenv is optional
    print("[CONFIG] dotenv: python-dotenv NOT INSTALLED, .env file will be ignored!")

# Print resolved key values at startup
_key = os.getenv("OPENAI_API_KEY", "")
_model = os.getenv("RETROSPECTIVE_LLM_MODEL", "gpt-4o-mini")
_provider = os.getenv("RETROSPECTIVE_LLM_PROVIDER", "auto")
print(f"[CONFIG] OPENAI_API_KEY present={bool(_key)}, length={len(_key)}")
print(f"[CONFIG] RETROSPECTIVE_LLM_MODEL={_model}")
print(f"[CONFIG] RETROSPECTIVE_LLM_PROVIDER={_provider}")

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings:
    app_name = "LogX POC API"
    api_prefix = "/api/v1"
    source_mode = "mock"

    # database_url = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'logx.db').as_posix()}") // for local 
    database_url = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT_DIR / 'logx.db').as_posix()}")
    # Heroku uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)


    allowed_origins_raw = os.getenv("ALLOWED_ORIGINS", "*")
    allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]

    attachments_dir = Path(os.getenv("ATTACHMENTS_DIR", str(ROOT_DIR / "storage" / "attachments")))

    embedding_provider = os.getenv("EMBEDDING_PROVIDER", "deterministic").strip().lower()
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
    embedding_dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "64"))

    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
    azure_openai_embedding_deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
    azure_openai_chat_deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "").strip()
    azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01").strip()

    vector_store_backend = os.getenv("VECTOR_STORE_BACKEND", "database").strip().lower()
    opensearch_url = os.getenv("OPENSEARCH_URL", "").strip()
    opensearch_index = os.getenv("OPENSEARCH_INDEX", "logx-node-embeddings").strip()
    opensearch_username = os.getenv("OPENSEARCH_USERNAME", "").strip()
    opensearch_password = os.getenv("OPENSEARCH_PASSWORD", "").strip()

    clustering_min_samples = int(os.getenv("CLUSTERING_MIN_SAMPLES", "6"))
    clustering_max_samples = int(os.getenv("CLUSTERING_MAX_SAMPLES", "5000"))

    intervention_enabled = os.getenv("INTERVENTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
    intervention_profile_key = os.getenv("INTERVENTION_PROFILE_KEY", "global").strip()
    intervention_similarity_threshold = float(os.getenv("INTERVENTION_SIMILARITY_THRESHOLD", "0.85"))
    intervention_history_match_count = int(os.getenv("INTERVENTION_HISTORY_MATCH_COUNT", "5"))

    # --- Dynamic properties: always read current env value ---
    # This ensures keys set after module import (or loaded from .env) are picked up.

    @property
    def openai_api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "").strip()

    @property
    def openai_base_url(self) -> str:
        return os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    @property
    def intervention_llm_model(self) -> str:
        return os.getenv("INTERVENTION_LLM_MODEL", "gpt-4o-mini").strip()

    intervention_llm_timeout_seconds = int(os.getenv("INTERVENTION_LLM_TIMEOUT_SECONDS", "14"))

    @property
    def retrospective_llm_provider(self) -> str:
        return os.getenv("RETROSPECTIVE_LLM_PROVIDER", "auto").strip().lower()

    @property
    def retrospective_llm_model(self) -> str:
        return os.getenv("RETROSPECTIVE_LLM_MODEL", "gpt-4o-mini").strip()

    retrospective_llm_timeout_seconds = int(os.getenv("RETROSPECTIVE_LLM_TIMEOUT_SECONDS", "24"))
    retrospective_default_days = int(os.getenv("RETROSPECTIVE_DEFAULT_DAYS", "7"))
    retrospective_max_trades = int(os.getenv("RETROSPECTIVE_MAX_TRADES", "250"))

    google_client_name = os.getenv("GOOGLE_CLIENT_NAME", "").strip()
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    session_secret_key = os.getenv("SECRET_KEY", "change-me").strip()
    frontend_base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").strip().rstrip("/")
    cookie_secure = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}


settings = Settings()
