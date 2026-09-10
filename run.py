"""
Root-level launcher for the Asiatech Sentiment Analysis API.

Run from the project root (``asiatech-sentiment-backend/``)::

    python run.py

This inserts the ``backend/`` directory onto ``sys.path`` and starts the
API over uvicorn. Reload is disabled by default to avoid accidental
production-like behavior during deployment; use ``APP_RELOAD=true`` only for
local development.
"""
import os
import sys
from pathlib import Path

# Ensure the backend/ directory is on sys.path so that "from app import …"
# works even when uvicorn is invoked from the project root.
_BACKEND_DIR = str(Path(__file__).resolve().parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import uvicorn  # noqa: E402


def main() -> None:
    reload_enabled = os.getenv("APP_RELOAD", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload_enabled,
    )


if __name__ == "__main__":
    main()
