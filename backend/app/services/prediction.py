"""Active prediction pipeline for the approved research model set.

The runtime honours the approach selected (and persisted) during training:
either an individual approved model (XGBoost / DeBERTa / RoBERTa / MiniLM) or
the approved weighted soft-voting ensemble (mDeBERTa + XLM-RoBERTa). Ensemble
weights are the values selected during training and persisted in
``model_metadata.json`` — they are never silently replaced by configuration
defaults.

The LIVE production sentiment model is Multilingual MiniLM — the only live
model. There is no inference fallback: if MiniLM cannot serve, the pipeline
raises and the API returns a clean 503. The transformers remain offline for
the free-tier RAM budget, and XGBoost is no longer run in the request path.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingHistory
from app.services.ensembles import (
    CLASS_ORDER,
    APPROVED_APPROACHES,
    ENSEMBLES,
    members_of,
    normalize_weights,
    soft_vote,
)
from app.services.minilm_service import minilm_service
from app.utils.logger import logger

# Multilingual MiniLM is the ONLY live model. The retired services (XGBoost,
# mDeBERTa, XLM-RoBERTa) are intentionally NOT imported here — importing their
# modules constructs singletons that load model weights at startup. They are
# only imported lazily by the offline training paths in training.py.

# LIVE inference model: Multilingual MiniLM (small quantized footprint fits the
# free-tier RAM budget) — the ONLY live model. There is deliberately no
# fallback: if its artifacts are missing or a prediction fails, the pipeline
# raises and the API surfaces a clean 503 instead of silently serving a
# different model. Legacy "ensemble" aliases resolve to the live single model.
_MODEL_KEYS = ("Multilingual MiniLM",)
_ENSEMBLE_NAME = "Multilingual MiniLM"
_XGB_COMPAT_NAME = "XGBoost"


def _usable(label: Optional[str], conf: Optional[float], probs: Optional[list]) -> bool:
    """A model output is only usable if the label is a known class AND every
    numeric value is finite. ``float('nan')`` passes ``is not None`` checks
    but is stored as NULL by SQLite and breaks NOT NULL constraints, and an
    NaN confidence once leaked into the predictions table as exactly that
    (IntegrityError on predictions.confidence_score). NaN/infinite outputs
    are treated as model failure, same as an exception."""
    if label not in CLASS_ORDER:
        return False
    values = [conf, *(probs or [])]
    try:
        return all(
            isinstance(v, (int, float)) and math.isfinite(float(v)) for v in values
        )
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

    Legacy aliases (``Ensemble`` / ``Ensemble (soft vote)``) map to the live
    single model (XGBoost); any other unrecognised name passes through unchanged
    so the caller can ignore non-approved (legacy) values.
    """
    if value is None:
        return ""
    normalized = value.strip()
    aliases = {
        "Ensemble": _ENSEMBLE_NAME,
        "Ensemble (soft vote)": _ENSEMBLE_NAME,
    }
    return aliases.get(normalized, normalized)


def get_production_algorithm(db: Session) -> str:
    """Return the currently selected approach (approved only).

    Uses the persisted ``is_production_model`` row and defaults to XGBoost
    when no database selection exists. Deployment metadata is an artifact
    manifest, not an authorization source for changing the active model.
    Legacy rows are ignored so they cannot gate active inference.
    """
    row = db.query(TrainingHistory).filter(TrainingHistory.is_production_model.is_(True)).first()
    if row:
        raw = row.algorithm.value if row.algorithm else None
        name = _normalize_algorithm_name(raw)
        if name in APPROVED_APPROACHES:
            return name

    # No persisted selection: default to the live production model
    # (Multilingual MiniLM).
    return _ENSEMBLE_NAME


def get_deployment_config(db: Session) -> dict:
    """Describe the currently selected approach.

    For an ensemble this includes the persisted member models and the
    persisted (trained) weights needed to reconstruct it at inference time.
    """
    name = get_production_algorithm(db)
    metadata = _load_deployment_metadata()
    if name in ENSEMBLES:
        members = metadata.get("ensemble_members") or members_of(name)
        stored_weights = metadata.get("ensemble_weights") or {}
        weights = normalize_weights(list(members), stored_weights)
        return {
            "production_model": name,
            "approach_type": "ensemble",
            "ensemble_members": list(members),
            "ensemble_weights": weights,
        }
    return {"production_model": name, "approach_type": "single"}



def run_prediction_pipeline(db: Session, text: str) -> dict:
    """Run the approved research model set on ``text`` and return per-model
    and official payloads.

    The official result follows the approach selected during training. When
    an ensemble is selected it is reconstructed here from its component
    models and the persisted weights via weighted soft voting.
    """
    start = time.perf_counter()

    # Backward-compat report fields: the legacy per-model outputs are None in
    # the live path (XGBoost is no longer run per-request; the transformers
    # stay offline for the RAM budget).
    xgb_label: Optional[str] = None
    xgb_conf: Optional[float] = None
    xgb_probs: Optional[list[float]] = None
    deberta_label: Optional[str] = None
    deberta_conf: Optional[float] = None
    deberta_probs: Optional[list[float]] = None
    roberta_label: Optional[str] = None
    roberta_conf: Optional[float] = None
    roberta_probs: Optional[list[float]] = None

    # LIVE production model: Multilingual MiniLM (quantized ONNX) — the only
    # live model. If its artifacts are missing, a prediction fails, or this
    # host lacks the RAM the ONNX path needs (see
    # MiniLMService.can_run_live_inference), the pipeline raises and the API
    # returns a clean 503. No silent fallback to another model.
    minilm_label: Optional[str] = None
    minilm_conf: Optional[float] = None
    minilm_probs: Optional[list[float]] = None

    if minilm_service.can_run_live_inference():
        try:
            minilm_label, minilm_conf, minilm_probs = minilm_service.predict(text)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"MiniLM prediction failed: {exc}")
        if minilm_label is not None and not _usable(minilm_label, minilm_conf, minilm_probs):
            logger.error("MiniLM returned an unusable output (NaN/invalid).")
            minilm_label, minilm_conf, minilm_probs = None, None, None
    else:
        logger.error("MiniLM not serving live inference on this host.")

    active_probs = {
        "Multilingual MiniLM": minilm_probs,
    }
    active_candidates = {
        "Multilingual MiniLM": (minilm_label, minilm_conf),
    }

    # Backward-compat "ensemble" report: with a single live member the soft
    # vote degenerates to that member's output (weight 1.0), using the
    # *persisted* weights when the stored production model matches, otherwise
    # equal member weights.
    metadata = _load_deployment_metadata()
    if metadata.get("production_model") == _ENSEMBLE_NAME:
        ensemble_weights = normalize_weights(list(_MODEL_KEYS), metadata.get("ensemble_weights"))
    else:
        ensemble_weights = normalize_weights(list(_MODEL_KEYS), {})

    ensemble_label: Optional[str] = None
    ensemble_conf: Optional[float] = None
    ensemble_probs: Optional[list[float]] = None
    if all(active_probs[key] is not None for key in _MODEL_KEYS):
        ensemble_label, ensemble_conf, ensemble_probs = soft_vote(
            {key: active_probs[key] for key in _MODEL_KEYS},
            ensemble_weights,
            list(_MODEL_KEYS),
        )

    # Official result follows the selected (persisted) approach.
    cfg = get_deployment_config(db)
    production_algo = cfg["production_model"]
    official_label: Optional[str] = None
    official_conf: Optional[float] = None

    if cfg["approach_type"] == "ensemble":
        member_probs = {m: active_probs.get(m) for m in cfg["ensemble_members"]}
        if all(value is not None for value in member_probs.values()):
            official_label, official_conf, _ = soft_vote(
                member_probs,
                cfg["ensemble_weights"],
                cfg["ensemble_members"],
            )
        else:
            production_algo = None  # selected ensemble not reconstructable
    elif cfg["approach_type"] == "single":
        lookup_name = (
            "Multilingual MiniLM"
            if production_algo == _XGB_COMPAT_NAME
            else production_algo
        )
        official_label, official_conf = active_candidates.get(lookup_name, (None, None))

    # No fallback chain: MiniLM is the only live model. If its output is
    # missing, fall through to the compat ensemble field (degenerates to the
    # same single-model result) and then a clean 503.

    if official_label is None and ensemble_label is not None:
        official_label = ensemble_label
        official_conf = ensemble_conf
        production_algo = _ENSEMBLE_NAME

    if official_label is None:
        raise RuntimeError(
            "No sentiment model is currently available. Train at least one model via /ml/train."
        )

    # Final guard: the persisted Prediction row declares confidence_score
    # NOT NULL, and SQLite stores NaN as NULL — so an official result with a
    # non-finite confidence must never be returned (it would crash the
    # submission with an IntegrityError). Fall through to a clean 503 instead.
    if not _usable(official_label, official_conf, None):
        raise RuntimeError(
            "All available sentiment models returned invalid outputs. "
            "Check the server logs and retrain or re-import the model artifacts."
        )

    processing_time_ms = (time.perf_counter() - start) * 1000

    return {
        "xgb_prediction": xgb_label,
        "xgb_confidence": xgb_conf,
        "deberta_prediction": deberta_label,
        "deberta_confidence": deberta_conf,
        "roberta_prediction": roberta_label,
        "roberta_confidence": roberta_conf,
        "minilm_prediction": minilm_label,
        "minilm_confidence": minilm_conf,
        "ensemble_prediction": ensemble_label,
        "ensemble_confidence": ensemble_conf,
        "ensemble_probabilities": ensemble_probs,
        "official_prediction": official_label,
        "algorithm_used": production_algo,
        "confidence_score": official_conf,
        "processing_time_ms": processing_time_ms,
    }

