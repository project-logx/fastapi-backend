from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _sqlite_column_names(engine: Engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {str(row["name"]) for row in rows}


def apply_lightweight_migrations(engine: Engine) -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return

    trade_columns = _sqlite_column_names(engine, "trades")
    if "computed_quality_score" not in trade_columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE trades ADD COLUMN computed_quality_score FLOAT DEFAULT 0.0"))
