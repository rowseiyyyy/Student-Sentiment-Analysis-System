"""Active prediction pipeline for the approved research model set.

The runtime honours the approach selected (and persisted) during training:
either an individual approved model (XGBoost / DeBERTa / RoBERTa / MiniLM) or
the approved weighted soft-voting ensemble (mDeBERTa + XLM-RoBERTa). Ensemble
weights are the values selected during training and persisted in
``model_metadata.json`` — they are never silently replaced by configuration
defaults.

The LIVE production sentiment model is Multilingual MiniLM, with XGBoost
(TF-IDF) as a ready fallback; both transformers remain offline for the
free-tier RAM budget.
"""
from __future__ import annotations

import json
import math
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingHistory
from app.services.deberta_service import mdeberta_service
from app.services.ensembles import (
    APPROVED_APPROACHES,
    ENSEMBLES,
    members_of,
    normalize_weights,
    soft_vote,
)
from app.services.minilm_service import minilm_service
from app.services.roberta_service import xlm_roberta_service
from app.services.xgboost_service import CLASS_ORDER, xgboost_service
from app.utils.logger import logger

# Compatibility names for integrations and tests that monkeypatch the former
# service attributes; both point to the new multilingual services.
deberta_service = mdeberta_service
roberta_service = xlm_roberta_service

# LIVE inference model: Multilingual MiniLM (small quantized footprint fits the
# free-tier RAM budget). XGBoost (TF-IDF) is kept as a ready fallback so a
# missing/failed MiniLM artifact never takes the submission endpoint down, and
# its output is still reported in the admin per-model breakdown.
# Legacy "ensemble" aliases resolve to the live single model.
_MODEL_KEYS = ("Multilingual MiniLM",)
_ENSEMBLE_NAME = "Multilingual MiniLM"
_LIVE_FALLBACK = "XGBoost (TF-IDF)"
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

    xgb_label: Optional[str] = None
    xgb_conf: Optional[float] = None
    xgb_probs: Optional[list[float]] = None
    deberta_label: Optional[str] = None
    deberta_conf: Optional[float] = None
    deberta_probs: Optional[list[float]] = None
    roberta_label: Optional[str] = None
    roberta_conf: Optional[float] = None
    roberta_probs: Optional[list[float]] = None

    if xgboost_service.is_ready():
        try:
            xgb_label, xgb_conf, xgb_probs = xgboost_service.predict(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"XGBoost prediction failed: {exc}")
            xgb_label, xgb_conf, xgb_probs = None, None, None
        if not _usable(xgb_label, xgb_conf, xgb_probs):
            logger.warning("XGBoost returned an unusable output (NaN/invalid) — excluded.")
            xgb_label, xgb_conf, xgb_probs = None, None, None

    # mDeBERTa and XLM-RoBERTa are intentionally NOT run in the live request
    # path (RAM budget — they previously OOM-crashed Render's 512 MB free
    # tier); the deberta_*/roberta_* fields remain None and are kept only for
    # historical/compat reporting. Offline evaluation and /ml/train still use
    # both transformer services.

    # LIVE production model: Multilingual MiniLM (quantized, per-prediction
    # build/unload). Falls back to XGBoost (TF-IDF) when its artifacts are
    # missing or a prediction fails, so submissions never hard-fail.
    minilm_label: Optional[str] = None
    minilm_conf: Optional[float] = None
    minilm_probs: Optional[list[float]] = None

    if minilm_service.is_ready():
        try:
            minilm_label, minilm_conf, minilm_probs = minilm_service.predict(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"MiniLM prediction failed: {exc}")
            minilm_label, minilm_conf, minilm_probs = None, None, None
        if not _usable(minilm_label, minilm_conf, minilm_probs):
            logger.warning("MiniLM returned an unusable output (NaN/invalid) — excluded.")
            minilm_label, minilm_conf, minilm_probs = None, None, None
    else:
        logger.warning("MiniLM artifacts not ready — falling back to XGBoost (TF-IDF) for live inference.")

    active_probs = {
        "Multilingual MiniLM": minilm_probs,
    }
    active_candidates = {
        "Multilingual MiniLM": (minilm_label, minilm_conf),
        "XGBoost (TF-IDF)": (xgb_label, xgb_conf),
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
            "XGBoost (TF-IDF)"
            if production_algo == _XGB_COMPAT_NAME or production_algo == _LIVE_FALLBACK
            else production_algo
        )
        official_label, official_conf = active_candidates.get(lookup_name, (None, None))

    # Fallbacks: the live model's output, then the ready XGBoost model, then
    # the backward-compat ensemble field (degenerates to the same single-model
    # result).
    if official_label is None:
        for algo in (*_MODEL_KEYS, _LIVE_FALLBACK):
            label, conf = active_candidates.get(algo, (None, None))
            if label is not None:
                official_label, official_conf, production_algo = label, conf, algo
                break

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

