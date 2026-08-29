"""Active prediction pipeline for the approved research model set.

The runtime honours the approach selected (and persisted) during training:
either an individual approved model (XGBoost / DeBERTa / RoBERTa) or one of
the four approved weighted soft-voting ensembles. Ensemble weights are the
values selected during training and persisted in ``model_metadata.json`` —
they are never silently replaced by configuration defaults.

Legacy model fields are no longer produced by the active pipeline; the
official result follows the persisted production approach.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingHistory
from app.services.deberta_service import deberta_service
from app.services.ensembles import (
    APPROVED_APPROACHES,
    ENSEMBLES,
    members_of,
    normalize_weights,
    soft_vote,
)
from app.services.roberta_service import roberta_service
from app.services.xgboost_service import xgboost_service

_MODEL_KEYS = ("XGBoost", "DeBERTa", "RoBERTa")
_TRIPLE_NAME = "XGBoost + DeBERTa + RoBERTa"


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

    Legacy aliases (``Ensemble`` / ``Ensemble (soft vote)``) map to the
    triple ensemble; any other unrecognised name passes through unchanged so
    the caller can ignore non-approved (legacy) values.
    """
    if value is None:
        return ""
    normalized = value.strip()
    aliases = {
        "Ensemble": _TRIPLE_NAME,
        "Ensemble (soft vote)": _TRIPLE_NAME,
    }
    return aliases.get(normalized, normalized)


def get_production_algorithm(db: Session) -> str:
    """Return the currently selected approach (approved only).

    Prefers the persisted ``is_production_model`` row, then the persisted
    deployment metadata, and finally defaults to XGBoost. Legacy rows are
    ignored so they cannot gate active inference.
    """
    row = db.query(TrainingHistory).filter(TrainingHistory.is_production_model.is_(True)).first()
    if row:
        raw = row.algorithm.value if row.algorithm else None
        name = _normalize_algorithm_name(raw)
        if name in APPROVED_APPROACHES:
            return name

    metadata = _load_deployment_metadata()
    production_model = metadata.get("production_model")
    name = _normalize_algorithm_name(str(production_model) if production_model else None)
    if name in APPROVED_APPROACHES:
        return name

    return "XGBoost"


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
        except Exception:  # noqa: BLE001
            xgb_label, xgb_conf, xgb_probs = None, None, None

    if deberta_service.is_ready():
        try:
            deberta_label, deberta_conf, deberta_probs = deberta_service.predict(text)
        except Exception:  # noqa: BLE001
            deberta_label, deberta_conf, deberta_probs = None, None, None

    if roberta_service.is_ready():
        try:
            roberta_label, roberta_conf, roberta_probs = roberta_service.predict(text)
        except Exception:  # noqa: BLE001
            roberta_label, roberta_conf, roberta_probs = None, None, None

    active_probs = {
        "XGBoost": xgb_probs,
        "DeBERTa": deberta_probs,
        "RoBERTa": roberta_probs,
    }
    active_candidates = {
        "XGBoost": (xgb_label, xgb_conf),
        "DeBERTa": (deberta_label, deberta_conf),
        "RoBERTa": (roberta_label, roberta_conf),
    }

    # Backward-compat "ensemble" report: the three-model soft vote, using the
    # *persisted* triple weights when the triple ensemble is the selected
    # approach, otherwise equal member weights.
    metadata = _load_deployment_metadata()
    if metadata.get("production_model") == _TRIPLE_NAME:
        triple_weights = normalize_weights(list(_MODEL_KEYS), metadata.get("ensemble_weights"))
    else:
        triple_weights = normalize_weights(list(_MODEL_KEYS), {})

    ensemble_label: Optional[str] = None
    ensemble_conf: Optional[float] = None
    ensemble_probs: Optional[list[float]] = None
    if all(active_probs[key] is not None for key in _MODEL_KEYS):
        ensemble_label, ensemble_conf, ensemble_probs = soft_vote(
            {key: active_probs[key] for key in _MODEL_KEYS},
            triple_weights,
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
        official_label, official_conf = active_candidates.get(production_algo, (None, None))

    # Fallbacks: any available approved model, then the triple ensemble.
    if official_label is None:
        for algo in _MODEL_KEYS:
            label, conf = active_candidates.get(algo, (None, None))
            if label is not None:
                official_label, official_conf, production_algo = label, conf, algo
                break

    if official_label is None and ensemble_label is not None:
        official_label = ensemble_label
        official_conf = ensemble_conf
        production_algo = _TRIPLE_NAME

    if official_label is None:
        raise RuntimeError(
            "No sentiment model is currently available. Train at least one model via /ml/train."
        )

    processing_time_ms = (time.perf_counter() - start) * 1000

    return {
        "xgb_prediction": xgb_label,
        "xgb_confidence": xgb_conf,
        "deberta_prediction": deberta_label,
        "deberta_confidence": deberta_conf,
        "roberta_prediction": roberta_label,
        "roberta_confidence": roberta_conf,
        "ensemble_prediction": ensemble_label,
        "ensemble_confidence": ensemble_conf,
        "ensemble_probabilities": ensemble_probs,
        "official_prediction": official_label,
        "algorithm_used": production_algo,
        "confidence_score": official_conf,
        "processing_time_ms": processing_time_ms,
    }

