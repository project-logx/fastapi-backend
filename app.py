from __future__ import annotations

import runpy
from pathlib import Path


def main() -> None:
    entrypoint = Path(__file__).resolve().parent / "frontend" / "app.py"
    runpy.run_path(str(entrypoint), run_name="__main__")


if __name__ == "__main__":
    main()