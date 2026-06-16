import time
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import engine


def wait_for_database(max_retries=10, delay=3):
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Database connected")
            return

        except OperationalError:
            print(
                f"Database not ready. Retrying "
                f"{attempt + 1}/{max_retries}"
            )
            time.sleep(delay)

    raise RuntimeError("Database unavailable")