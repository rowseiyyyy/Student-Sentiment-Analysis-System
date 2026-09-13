"""Startup download of private HuggingFace Hub artifacts into local ``app/ml`` paths.

This module *only guarantees the expected files exist on disk* — it does not load
anything into memory. Loading stays with the existing service singletons
(``transformer_service`` / ``xgboost_service``) via their ``_load`` / ``_try_load``
methods, so this layer slots into the app's existing load split without replacing it.

Downloads are skipped when the target artifacts already exist locally, so repeated
restarts (and the pre-committed ``app/ml/`` files in this repo) do not re-download.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import settings
from app.utils.logger import logger


def _transformer_ready(path: Path, quantized_file: str) -> bool:
    """Mirror ``TransformerSentimentService.is_ready``: a config and the quantized
    state_dict are present (the repos carry config.json/tokenizer + the .pt; the
    full-size safetensors checkpoints are no longer used for inference)."""
    return (
        path.exists()
        and (path / "config.json").exists()
        and (path / quantized_file).exists()
    )


def _classical_ready() -> bool:
    """Mirror ``main._models_are_ready``: XGB model + vectorizer + label encoder present."""
    return all(
        path.exists()
        for path in (
            settings.XGB_MODEL_PATH,
            settings.XGB_TFIDF_VECTORIZER_PATH,
            settings.XGB_LABEL_ENCODER_PATH,
        )
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


def _download_classical() -> None:
    """Fetch XGBoost + TF-IDF and generate the (unused-for-inference) label encoder.

    The hub repo (```rowseiy/xgb-tfidf-sentiment``) contains only two files:
      * ``xgboost_model.pkl``      -> copied to ``XGB_MODEL_PATH``
      * ``xgboost_vectorizer.pkl`` -> copied to ``XGB_TFIDF_VECTORIZER_PATH``

    There is no label-encoder file in the repo, and ``xgboost_service`` never reads
    one (it only writes it in ``save()``; ``CLASS_ORDER`` drives prediction). However,
    both ``_classical_ready()`` and ``main._models_are_ready()`` require the file to
    exist, so we generate a minimal one — matching what ``XGBoostService.save()``
    produces — so a fresh boot doesn't fail readiness over a file that isn't used
    for inference.
    """
    from huggingface_hub import hf_hub_download

    settings.ML_DIR.mkdir(parents=True, exist_ok=True)

    def _fetch(filename: str, target: Path) -> None:
        downloaded = hf_hub_download(
            repo_id=settings.HF_XGB_TFIDF_REPO,
            filename=filename,
            token=settings.HF_TOKEN or None,
        )
        shutil.move(downloaded, target)

    _fetch("xgboost_model.pkl", settings.XGB_MODEL_PATH)
    _fetch("xgboost_vectorizer.pkl", settings.XGB_TFIDF_VECTORIZER_PATH)

    # Minimal label encoder matching XGBoostService.save():
    # {"classes": CLASS_ORDER}. Imported lazily to avoid constructing the
    # XGBoostService singleton at module load time.
    from app.services.xgboost_service import CLASS_ORDER

    settings.XGB_LABEL_ENCODER_PATH.write_text(
        json.dumps({"classes": CLASS_ORDER}), encoding="utf-8"
    )


def ensure_hub_artifacts() -> bool:
    """Download any missing private artifacts; return True if anything was fetched.

    Safe to call on every startup: when local files already exist it is a no-op.
    Runs the three transformer/XGBoost/TF-IDF downloads in the same order the
    readiness check / services expect.
    """
    if not settings.HF_TOKEN:
        logger.warning("HF_TOKEN is not set — skipping private hub downloads.")
        return False

    downloaded = False

    # mDeBERTa is intentionally NOT downloaded at startup: like XLM-RoBERTa it
    # is excluded from the live inference path (RAM budget — its quantized
    # build/unload still OOM-crashed Render's 512 MB free tier). Its repo,
    # config/tokenizer, and trained weights remain available for offline
    # evaluation, reporting, and /ml/train fine-tuning.

    if _classical_ready():
        logger.info("XGBoost / TF-IDF artifacts already present locally — skipping download.")
    else:
        logger.info(f"Downloading private XGBoost / TF-IDF repo: {settings.HF_XGB_TFIDF_REPO}")
        _download_classical()
        downloaded = True

    return downloaded
