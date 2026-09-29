"""Startup download of the private mBERT Hybrid HuggingFace Hub artifacts.

mBERT Hybrid is the ONLY live model, so it is the only artifact set fetched at
startup. This module only guarantees the expected files exist on disk - it does
not load anything into memory; loading stays with the ``mbert_service``
singleton.

Downloads are skipped when the target artifacts already exist locally, so
repeated restarts (and the pre-committed ``app/ml/`` files in this repo) do
not re-download.
"""
from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.utils.logger import logger


def _mbert_ready(path: Path) -> bool:
    """The encoder config/weights and the hybrid-head classifier are present."""
    return (
        (path / "config.json").exists()
        and (path / settings.MBERT_SAFETENSORS_FILE).exists()
        and (path / settings.MBERT_CLASSIFIER_FILE).exists()
    )


def _snapshot(repo_id: str, local_dir: Path) -> None:
    """Fetch every file in ``repo_id`` into ``local_dir`` (private repo via HF_TOKEN)."""
    from huggingface_hub import snapshot_download

    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        token=settings.HF_TOKEN or None,
    )


def ensure_hub_artifacts() -> bool:
    """Download any missing mBERT artifacts; return True if anything was fetched.

    Safe to call on every startup: when local files already exist it is a no-op.
    """
    if not settings.HF_TOKEN:
        logger.warning("HF_TOKEN is not set - skipping private hub downloads.")
        return False

    downloaded = False

    # mBERT Hybrid IS the only live production sentiment model - its frozen
    # encoder weights + hybrid-head classifier are required for real-time
    # inference, and it is the only artifact set fetched here.
    if _mbert_ready(settings.MBERT_MODEL_PATH):
        logger.info(
            "mBERT Hybrid artifacts already present locally - skipping download."
        )
    else:
        logger.info(f"Downloading private mBERT Hybrid repo: {settings.HF_MBERT_REPO}")
        _snapshot(settings.HF_MBERT_REPO, settings.MBERT_MODEL_PATH)
        downloaded = True

    return downloaded
