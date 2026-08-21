"""
Root-level launcher for the Asiatech Sentiment Analysis API.

Run from the project root (``asiatech-sentiment-backend/``)::

    python run.py

This inserts the ``backend/`` directory onto ``sys.path`` and starts the
development server via ``uvicorn main:app``, so the app can be launched from
the root without tripping over the ``No module named 'app'`` error.
"""
import sys
from pathlib import Path

# Ensure the backend/ directory is on sys.path so that "from app import …"
# works even when uvicorn is invoked from the project root.
_BACKEND_DIR = str(Path(__file__).resolve().parent / "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import uvicorn  # noqa: E402


def main() -> None:
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
