"""
Launcher for the Asiatech Sentiment Analysis API.

Run from the ``backend/`` directory::

    .venv\\Scripts\\python.exe run.py

This is a convenience wrapper around ``uvicorn main:app``. It ensures the
``backend/`` directory is on ``sys.path`` and starts the development server
with auto-reload, exactly as documented in the README.

Equivalent manual command::

    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import sys
from pathlib import Path

# Ensure the backend/ directory is on sys.path so that "from app import …"
# works even when uvicorn is invoked from a different working directory.
_backend_dir = str(Path(__file__).resolve().parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

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
