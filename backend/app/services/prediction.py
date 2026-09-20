
"""Active prediction pipeline for the approved research model set.

The LIVE production sentiment model is Multilingual MiniLM — the only live
model. There is no inference fallback: if MiniLM cannot serve, the pipeline
raises and the API returns a clean 503. The classical research models
(SVM, Naive Bayes, Logistic Regression) are offline-only and are never run
in the request path.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingHistory
from app.services.ensembles import CLASS_ORDER, APPROVED_APPROACHES
from app.services.minilm_service import minilm_service
from app.utils.logger import logger

# Multilingual MiniLM is the ONLY live model. The classical research services
# (SVM, Naive Bayes, Logistic Regression) are intentionally NOT imported here —
# they are only used by the offline training paths in training.py.
LIVE_MODEL_NAME = "Multilingual MiniLM"


def _usable(label: Optional[str], conf: Optional[float]) -> bool:
    """A model output is only usable if the label is a known class AND the
    confidence is finite. ``float('nan')`` passes ``is not None`` checks but
    is stored as NULL by SQLite and breaks NOT NULL constraints, and an NaN
    confidence once leaked into the predictions table as exactly that
    (IntegrityError on predictions.confidence_score). NaN/infinite outputs
    are treated as model failure, same as an exception."""
    if label not in CLASS_ORDER:
        return False
    try:
        return conf is not None and math.isfinite(float(conf))
    except (TypeError, ValueError):
        return False


def _load_deployment_metadata() -> dict:
    if settings.MODEL_METADATA_PATH.exists():
        try:
            with open(settings.MODEL_METADATA_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _normalize_algorithm_name(value: str | None) -> str:
    """Map a stored approach name to a canonical approved approach name.

    Any unrecognised name passes through unchanged so the caller can ignore
    non-approved (legacy) values."""
    if value is None:
        return ""
    return value.strip()


def get_production_algorithm(db: Session) -> str:
    """Return the currently selected approach (approved only).

    Uses the persisted ``is_production_model`` row and defaults to
    Multilingual MiniLM when no database selection exists. Deployment
    metadata is an artifact-level hint only — the database wins."""
    current = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.is_production_model.is_(True))
        .first()
    )
    if current is not None:
        name = _normalize_algorithm_name(current.algorithm.value)
        if name in APPROVED_APPROACHES:
            return name
    metadata = _load_deployment_metadata()
    name = _normalize_algorithm_name(metadata.get("production_model"))
    if name in APPROVED_APPROACHES:
        return name
    return LIVE_MODEL_NAME


def get_deployment_config(db: Session) -> dict:
    """Return the inference configuration for the selected production model.

    Multilingual MiniLM is the only live model, so the config is always a
    single-model configuration."""
    return {
        "production_model": get_production_algorithm(db),
        "approach_type": "single",
        "ensemble_members": [],
        "ensemble_weights": {},
    }


def run_prediction_pipeline(db: Session, text: str) -> dict:
    """Run the live prediction pipeline for one comment.

    Only Multilingual MiniLM performs inference. The classical research
    models (SVM, Naive Bayes, Logistic Regression) never run in the request
    path — their result fields are always None. There is no inference
    fallback: if MiniLM cannot serve, a RuntimeError is raised and the API
    returns a clean 503.
    """
    start = time.perf_counter()

    # ----- LIVE model: Multilingual MiniLM --------------------------------
    minilm_label: Optional[str] = None
    minilm_conf: Optional[float] = None
    minilm_probs: Optional[list[float]] = None
    if minilm_service.can_run_live_inference():
        try:
            minilm_label, minilm_conf, minilm_probs = minilm_service.predict(text)
        except Exception as exc:  # noqa: BLE001
            logger.error("Multilingual MiniLM inference failed: %s", exc)

    # ----- Classical research models: NOT run in the request path ---------
    svm_label = svm_conf = None
    naive_bayes_label = naive_bayes_conf = None
    logreg_label = logreg_conf = None

    official_label = minilm_label
    official_conf = minilm_conf
    production_algo = LIVE_MODEL_NAME

    if not _usable(official_label, official_conf):
        raise RuntimeError(
            "Multilingual MiniLM (the only live sentiment model) is unavailable. "
            "Check the server logs and restart, or disable the memory guard via "
            "MINILM_MIN_RAM_MB=0 if the host has enough RAM."
        )

    processing_time_ms = (time.perf_counter() - start) * 1000

    return {
        "svm_prediction": svm_label,
        "svm_confidence": svm_conf,
        "naive_bayes_prediction": naive_bayes_label,
        "naive_bayes_confidence": naive_bayes_conf,
        "logistic_regression_prediction": logreg_label,
        "logistic_regression_confidence": logreg_conf,
        "minilm_prediction": minilm_label,
        "minilm_confidence": minilm_conf,
        "official_prediction": official_label,
        "algorithm_used": production_algo,
        "confidence_score": official_conf,
        "processing_time_ms": processing_time_ms,
    }

