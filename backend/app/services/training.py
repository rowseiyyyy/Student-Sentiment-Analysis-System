"""Training orchestration for the approved 4-model research set.

Approved models (all trained on an identical leakage-safe split; metrics are
computed on the untouched final test set):

    1. SVM (TF-IDF)
    2. Naive Bayes (TF-IDF)
    3. Logistic Regression (TF-IDF)
    4. Multilingual MiniLM — the ONLY live production model

Colab training runs can be imported via ``import_training_results`` (the
``POST /ml/import-results`` endpoint) — no local training is required.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingAlgorithm, TrainingHistory, TrainingStatus
from app.services.minilm_service import minilm_service
from app.services.ensembles import CLASS_ORDER, SINGLE_MODELS, APPROVED_APPROACHES
from app.utils.logger import logger

# The classical research services (SVM / Naive Bayes / Logistic Regression)
# are imported lazily inside run_full_training so importing this module (and
# therefore booting the app) never constructs or loads them.

REQUIRED_COLUMNS = {"comment", "sentiment"}
VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}
VALID_CATEGORIES = {"Faculty", "Staff", "Payment", "Facilities"}
RESPONSE_COLUMN_ALIASES = ("comment", "comments", "feedback", "response", "responses", "remarks", "review", "text")
LABEL_COLUMN_ALIASES = ("sentiment", "label")

# The ONLY model allowed to serve live production inference. Everything else
# in TrainingHistory (SVM, Naive Bayes, Logistic Regression) is research data
# and is display-only.
LIVE_MODEL_NAME = "Multilingual MiniLM"

# ---------------------------------------------------------------------------
# Colab export -> canonical approach-name resolution
# ---------------------------------------------------------------------------

def _canonicalize_key(key) -> str:
    """Lowercase and strip everything except a-z / 0-9 for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def colab_key_to_approach(key) -> str | None:
    """Resolve a Colab-export model key to a canonical approved approach name."""
    canonical = _canonicalize_key(key)
    if canonical in ("svm", "svc", "supportvectormachine"):
        return "SVM"
    if canonical in ("naivebayes", "nb", "multinomialnb"):
        return "Naive Bayes"
    if canonical in ("logisticregression", "logreg", "lr"):
        return "Logistic Regression"
    if "minilm" in canonical:
        return LIVE_MODEL_NAME
    return None


APPROACH_TO_ALGORITHM: dict[str, TrainingAlgorithm] = {
    "SVM": TrainingAlgorithm.SVM,
    "Naive Bayes": TrainingAlgorithm.NAIVE_BAYES,
    "Logistic Regression": TrainingAlgorithm.LOGISTIC_REGRESSION,
    "Multilingual MiniLM": TrainingAlgorithm.MINILM,
}




class DatasetValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# Metrics + persistence helpers
# ---------------------------------------------------------------------------

def _metrics_for_labels(y_true: Iterable[str], y_pred: Iterable[str]) -> dict:
    from sklearn.metrics import (  # lazy: only imported inside this offline-only helper
        accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    y_true_arr = np.asarray(list(y_true), dtype=object)
    y_pred_arr = np.asarray(list(y_pred), dtype=object)
    labels = list(CLASS_ORDER)
    report = classification_report(
        y_true_arr, y_pred_arr, labels=labels, target_names=labels,
        output_dict=True, zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true_arr, y_pred_arr)),
        "precision": float(precision_score(y_true_arr, y_pred_arr, average="weighted", zero_division=0)),
        "recall": float(recall_score(y_true_arr, y_pred_arr, average="weighted", zero_division=0)),
        "f1_score": float(f1_score(y_true_arr, y_pred_arr, average="weighted", zero_division=0)),
        "macro_f1": float(f1_score(y_true_arr, y_pred_arr, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true_arr, y_pred_arr, average="weighted", zero_division=0)),
        "labels": labels,
        "confusion_matrix": confusion_matrix(y_true_arr, y_pred_arr, labels=labels).tolist(),
        "classification_report": report,
        "per_class": {
            label: {
                "precision": float(report.get(label, {}).get("precision", 0.0)),
                "recall": float(report.get(label, {}).get("recall", 0.0)),
                "f1": float(report.get(label, {}).get("f1-score", 0.0)),
                "support": int(report.get(label, {}).get("support", 0)),
            }
            for label in labels
        },
    }


def _split_dataset(df):
    from sklearn.model_selection import train_test_split  # lazy: only in this offline-only helper

    labels = df["sentiment"].tolist()
    idx = np.arange(len(df))
    idx_train_dev, idx_test = train_test_split(
        idx, test_size=settings.TEST_SIZE, random_state=settings.RANDOM_STATE, stratify=labels,
    )
    dev_df = df.iloc[idx_train_dev].reset_index(drop=True)
    test_df = df.iloc[idx_test].reset_index(drop=True)
    dev_labels = dev_df["sentiment"].tolist()
    idx_train, idx_val = train_test_split(
        np.arange(len(dev_df)), test_size=0.25,
        random_state=settings.RANDOM_STATE, stratify=dev_labels,
    )
    train_df = dev_df.iloc[idx_train].reset_index(drop=True)
    val_df = dev_df.iloc[idx_val].reset_index(drop=True)
    return train_df, val_df, test_df


def _persist_history(
    db: Session,
    history: TrainingHistory,
    metrics: dict,
    status: TrainingStatus,
    commit: bool = True,
) -> None:
    history.status = status
    history.accuracy = metrics.get("accuracy")
    history.precision = metrics.get("precision")
    history.recall = metrics.get("recall")
    history.f1_score = metrics.get("f1_score")
    history.macro_f1 = metrics.get("macro_f1")
    history.weighted_f1 = metrics.get("weighted_f1")
    history.training_time_seconds = metrics.get("training_time_seconds")
    history.inference_time_ms = metrics.get("inference_time_ms")
    history.memory_usage_mb = metrics.get("memory_usage_mb")
    history.confusion_matrix = {"labels": metrics.get("labels"), "matrix": metrics.get("confusion_matrix")}
    history.classification_report = metrics.get("classification_report")
    history.hyperparameters = metrics.get("hyperparameters")
    if commit:
        db.commit()


def _mark_production_model(
    db: Session, algorithm: TrainingAlgorithm, commit: bool = True
) -> None:
    db.query(TrainingHistory).update({TrainingHistory.is_production_model: False})
    latest = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.algorithm == algorithm)
        .order_by(TrainingHistory.created_at.desc())
        .first()
    )
    if latest:
        latest.is_production_model = True
    if commit:
        db.commit()


def register_hub_models(db: Session, production: str) -> dict:
    """Idempotent first-boot bootstrap: record the hub-hosted MiniLM in TrainingHistory.

    HF hubs serve weights, not eval metrics, so metric columns stay NULL. This
    only fills *gaps* on a fresh database — it never overwrites an existing row,
    and it only sets a production model when none is currently selected. That makes
    the admin panel model list / performance comparison and the
    ``TrainingHistory.is_production_model`` selection (used by the prediction
    pipeline) work without a manual /ml/import-results on first boot.

    Returns ``{"registered": [...], "production_model": str | None}``.
    """
    if production not in APPROVED_APPROACHES:
        production = LIVE_MODEL_NAME

    registered: list[str] = []
    # Multilingual MiniLM is the only live model — only its row is bootstrapped.
    algorithm = APPROACH_TO_ALGORITHM[LIVE_MODEL_NAME]
    exists = db.query(TrainingHistory).filter(TrainingHistory.algorithm == algorithm).first()
    if exists is None:
        db.add(TrainingHistory(
            algorithm=algorithm,
            status=TrainingStatus.COMPLETED,
            dataset_filename="huggingface_hub",
            notes="Registered from private HuggingFace Hub artifacts at startup.",
        ))
        registered.append(LIVE_MODEL_NAME)

    selected: str | None = None
    current_prod = db.query(TrainingHistory).filter(TrainingHistory.is_production_model.is_(True)).first()
    if current_prod is None:
        db.flush()  # persist new rows so _mark_production_model can find them
        _mark_production_model(db, TrainingAlgorithm.MINILM, commit=False)
        selected = LIVE_MODEL_NAME

    if registered or selected is not None:
        sync_deployment_metadata(db, LIVE_MODEL_NAME)
        db.commit()

    return {"registered": registered, "production_model": selected}


def _write_comparison_artifacts(results: dict, best_algorithm: str, selection_metric: str = "weighted_f1") -> None:
    settings.ML_DIR.mkdir(parents=True, exist_ok=True)
    best_metrics = results.get(best_algorithm, {})
    selection_score = float(best_metrics.get(selection_metric, best_metrics.get("weighted_f1", 0.0)))

    metadata: dict = {
        "production_model": best_algorithm,
        "approach_type": "single",
        "selection_metric": selection_metric,
        "selection_score": selection_score,
        "models": results,
    }

    with open(settings.COMPARISON_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"best_model": best_algorithm, "rows": results}, fh, indent=2)
    with open(settings.MODEL_METADATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)


def sync_deployment_metadata(db: Session, algorithm_name: str) -> None:
    """Rewrite the ``production_model`` section of ``model_metadata.json`` to
    match ``algorithm_name``. Only single (approved) approaches exist now."""
    settings.ML_DIR.mkdir(parents=True, exist_ok=True)

    metadata: dict = {}
    if settings.MODEL_METADATA_PATH.exists():
        try:
            with open(settings.MODEL_METADATA_PATH, encoding="utf-8") as fh:
                metadata = json.load(fh)
        except (json.JSONDecodeError, OSError):
            metadata = {}

    metadata["production_model"] = algorithm_name
    metadata["approach_type"] = "single"
    metadata.pop("ensemble_members", None)
    metadata.pop("ensemble_weights", None)

    with open(settings.MODEL_METADATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)


def _normalise_category(value: str) -> str:
    """Map free-text dataset category names to the canonical set."""
    val = value.strip().lower()
    aliases = {
        "payments": "Payment",
        "faculties": "Faculty",
        "faculty": "Faculty",
        "staffs": "Staff",
        "staff": "Staff",
        "facilities": "Facilities",
        "facility": "Facilities",
    }
    if val in aliases:
        return aliases[val]
    return val.capitalize()


def _resolve_dataset_column(columns: list[str], explicit: str | None, aliases: tuple[str, ...], kind: str) -> str:
    normalized = {column.strip().lower(): column for column in columns}
    if explicit:
        key = explicit.strip().lower()
        if key not in normalized:
            raise DatasetValidationError(f"Selected {kind} column '{explicit}' was not found.")
        return normalized[key]
    matches = [normalized[alias] for alias in aliases if alias in normalized]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise DatasetValidationError(f"Dataset is missing a {kind} column. Expected one of: {', '.join(aliases)}")
    raise DatasetValidationError(f"Multiple possible {kind} columns found: {matches}. Select one explicitly.")


def load_and_validate_dataset(
    csv_path: Path,
    response_column: str | None = None,
    label_column: str | None = None,
) -> "pd.DataFrame":
    df = pd.read_csv(csv_path)
    original_columns = [str(column) for column in df.columns]
    response_source = _resolve_dataset_column(original_columns, response_column, RESPONSE_COLUMN_ALIASES, "response")
    label_source = _resolve_dataset_column(original_columns, label_column, LABEL_COLUMN_ALIASES, "sentiment label")
    df = df.rename(columns={response_source: "comment", label_source: "sentiment"})

    required = ["comment", "sentiment"]
    if "category" in df.columns:
        required.append("category")
    df = df.dropna(subset=required)
    df["sentiment"] = df["sentiment"].astype(str).str.strip().str.capitalize()

    invalid_sentiments = set(df["sentiment"].unique()) - VALID_SENTIMENTS
    if invalid_sentiments:
        raise DatasetValidationError(f"Invalid sentiment labels found: {invalid_sentiments}")

    if "category" in df.columns:
        df["category"] = df["category"].astype(str).str.strip().map(_normalise_category)
        invalid_categories = set(df["category"].unique()) - VALID_CATEGORIES
        if invalid_categories:
            raise DatasetValidationError(f"Invalid categories found: {invalid_categories}")

    if len(df) < 30:
        raise DatasetValidationError("Dataset must contain at least 30 labeled rows to train reliably.")

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Colab metrics import (POST /ml/import-results)
# ---------------------------------------------------------------------------

def _normalize_colab_model(model: dict, labels: list[str]) -> dict:
    """Convert one raw Colab model block into the persisted metrics shape."""
    per_class = model.get("per_class") or {}
    report: dict = {"accuracy": model.get("accuracy")}
    macro_vals: list[float] = []
    for label in labels:
        pc = per_class.get(label) or {}
        report[label] = {
            "precision": pc.get("precision"),
            "recall": pc.get("recall"),
            "f1-score": pc.get("f1"),
            "support": pc.get("support"),
        }
        if pc.get("f1") not in (None, ""):
            macro_vals.append(float(pc["f1"]))
    if macro_vals:
        report["macro avg"] = {"f1-score": sum(macro_vals) / len(macro_vals)}
    return {
        "accuracy": model.get("accuracy"),
        "precision": model.get("precision_weighted") or model.get("precision"),
        "recall": model.get("recall_weighted") or model.get("recall"),
        "f1_score": model.get("weighted_f1") or model.get("f1_score"),
        "macro_f1": model.get("macro_f1"),
        "weighted_f1": model.get("weighted_f1"),
        "labels": labels,
        "confusion_matrix": model.get("confusion_matrix"),
        "classification_report": report,
        "training_time_seconds": model.get("training_time_seconds"),
        "inference_time_ms": model.get("inference_time_ms"),
        "memory_usage_mb": model.get("memory_usage_mb"),
        "hyperparameters": model.get("hyperparameters"),
    }


def normalize_metrics_payload(payload: dict) -> tuple[dict[str, dict], str | None]:
    """Normalize a Colab ``dashboard_export.json`` into
    ``{canonical_approach: metrics}`` plus the recommended production model.

    Two shapes are accepted:

    * **Colab export**: approaches nested under a top-level ``"models"``
      dict (keys like ``svm`` / ``naive_bayes`` / ``logistic_regression`` /
      ``minilm``), with the recommendation in
      ``recommended_production_model`` (or ``best_model``).
    * **Rows shape** (what the admin client / tests send): a top-level
      ``{"rows": {approach: metrics}, "best_model": ...}`` mapping whose
      keys are already canonical approach names.
    """
    if not isinstance(payload, dict):
        raise DatasetValidationError("Metrics JSON must be an object.")

    # Rows shape: keys are already canonical approach names.
    rows = payload.get("rows")
    if isinstance(rows, dict) and not isinstance(payload.get("models"), dict):
        metrics_by_algorithm: dict[str, dict] = {}
        for approach, metrics in rows.items():
            canonical = colab_key_to_approach(approach) or str(approach).strip()
            if not isinstance(metrics, dict) or canonical not in APPROVED_APPROACHES:
                logger.warning(f"Skipping unrecognized imported approach: {approach}")
                continue
            metrics_by_algorithm[canonical] = metrics
        recommended_raw = payload.get("recommended_production_model") or payload.get("best_model")
        recommended = colab_key_to_approach(recommended_raw) or (
            str(recommended_raw).strip() if isinstance(recommended_raw, str) else None
        )
        if recommended not in APPROVED_APPROACHES:
            recommended = None
        return metrics_by_algorithm, recommended

    label_map = payload.get("label_map") or {}
    if isinstance(label_map, dict):
        labels = [str(name) for name in label_map.values()] if label_map else list(CLASS_ORDER)
    else:
        labels = [str(n) for n in label_map] or list(CLASS_ORDER)

    metrics_by_algorithm: dict[str, dict] = {}
    for key, model in (payload.get("models") or {}).items():
        approach = colab_key_to_approach(key)
        if approach is None or not isinstance(model, dict):
            continue
        metrics_by_algorithm[approach] = _normalize_colab_model(model, labels)

    recommended_raw = payload.get("recommended_production_model") or payload.get("best_model")
    recommended = colab_key_to_approach(recommended_raw) if recommended_raw else None
    return metrics_by_algorithm, recommended


def import_training_results(
    db: Session,
    metrics_by_algorithm: dict[str, dict],
    dataset_filename: str | None = None,
    set_production: str | None = None,
) -> dict:
    """Persist imported metrics as TrainingHistory rows and select production.

    Only Multilingual MiniLM rows can be marked ``is_production_model``; the
    classical research models (SVM / Naive Bayes / Logistic Regression) are
    stored display-only. Returns a summary dict for the API response.

    ``metrics_by_algorithm`` also accepts the Colab ``dashboard_export``
    shape (``{"rows": {...}, "best_model": ...}``) for convenience — the
    rows mapping is unwrapped before persistence.
    """
    rows = metrics_by_algorithm.get("rows") if isinstance(metrics_by_algorithm, dict) else None
    best_model_raw: str | None = None
    if isinstance(rows, dict):
        best_model_raw = metrics_by_algorithm.get("best_model")
        metrics_by_algorithm = rows
        if set_production is None and isinstance(best_model_raw, str):
            set_production = colab_key_to_approach(best_model_raw) or best_model_raw
    imported_algorithms: list[str] = []
    for approach, metrics in metrics_by_algorithm.items():
        algorithm = APPROACH_TO_ALGORITHM.get(approach)
        if algorithm is None or approach not in APPROVED_APPROACHES:
            logger.warning(f"Skipping unrecognized imported approach: {approach}")
            continue
        history = TrainingHistory(
            algorithm=algorithm,
            dataset_filename=dataset_filename,
            status=TrainingStatus.COMPLETED,
            is_production_model=False,
        )
        db.add(history)
        db.flush()
        _persist_history(db, history, metrics, TrainingStatus.COMPLETED, commit=False)
        imported_algorithms.append(approach)

    if not imported_algorithms:
        db.rollback()
        raise DatasetValidationError("No approved approaches found in the metrics payload.")

    requested = set_production or LIVE_MODEL_NAME
    if requested in APPROVED_APPROACHES and requested != LIVE_MODEL_NAME:
        # Research-only models can never serve live inference — keep the live
        # model as production and just log the requested approach.
        logger.warning(
            f"Requested production model '{requested}' is research-only; "
            f"production stays on '{LIVE_MODEL_NAME}'."
        )
    _mark_production_model(db, TrainingAlgorithm.MINILM, commit=False)
    db.commit()

    # Surface the best-scoring imported approach as the *recommendation*
    # (research comparison only — never promoted to production).
    best_imported: str | None = None
    best_score = float("-inf")
    for approach in imported_algorithms:
        score = metrics_by_algorithm.get(approach, {}).get("weighted_f1")
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        if score > best_score:
            best_score = score
            best_imported = approach

    return {
        "imported_algorithms": imported_algorithms,
        "production_model": LIVE_MODEL_NAME,
        "recommended_model": best_imported,
    }


# ---------------------------------------------------------------------------
# Local training pipeline (scripts/train_models.py)
# ---------------------------------------------------------------------------

def _run_minilm_eval(test_df) -> dict:
    """Evaluate the pretrained Multilingual MiniLM on the held-out test set.

    MiniLM is not fine-tuned here (it is trained in Colab); this produces
    leakage-safe test metrics for the comparison table.
    """
    texts = test_df["comment"].astype(str).tolist()
    labels = test_df["sentiment"].tolist()
    preds: list[str] = []
    for text in texts:
        label, _conf, _probs = minilm_service.predict(text)
        preds.append(label)
    return _metrics_for_labels(labels, preds)


def run_full_training(
    db: Session,
    csv_path: Path,
    response_column: str | None = None,
    label_column: str | None = None,
) -> dict:
    """Train the approved model set (SVM, Naive Bayes, Logistic Regression,
    Multilingual MiniLM) on ``csv_path`` and persist everything.

    All approaches are evaluated on the SAME untouched test split (leakage
    safe). Production stays on Multilingual MiniLM; the classical models are
    research results only. Returns ``{"results", "best_model"}``.
    """
    from app.services.classical_service import (
        logistic_regression_service,
        naive_bayes_service,
        svm_service,
    )

    df = load_and_validate_dataset(csv_path, response_column, label_column)
    train_df, val_df, test_df = _split_dataset(df)

    train_texts = train_df["comment"].astype(str).tolist()
    train_labels = train_df["sentiment"].tolist()
    test_texts = test_df["comment"].astype(str).tolist()
    test_labels = test_df["sentiment"].tolist()

    results: dict[str, dict] = {}
    started = time.perf_counter()

    for name, service in (
        ("SVM", svm_service),
        ("Naive Bayes", naive_bayes_service),
        ("Logistic Regression", logistic_regression_service),
    ):
        logger.info(f"Training {name}...")
        results[name] = service.train_on_split(train_texts, train_labels, test_texts, test_labels)

    logger.info("Evaluating Multilingual MiniLM on the held-out test set...")
    try:
        results[LIVE_MODEL_NAME] = _run_minilm_eval(test_df)
    except Exception as exc:  # noqa: BLE001 — MiniLM eval is best-effort offline
        logger.error(f"MiniLM evaluation failed (skipping its row): {exc}")

    elapsed = time.perf_counter() - started
    logger.info(f"Full training pipeline completed in {elapsed:.1f}s")

    # Best classical result by weighted F1 — informational only; production
    # remains Multilingual MiniLM regardless.
    best_classical = max(
        (n for n in results if n != LIVE_MODEL_NAME),
        key=lambda n: float(results[n].get("weighted_f1") or 0.0),
        default=None,
    )

    # Persist a TrainingHistory row per approach.
    for approach, metrics in results.items():
        algorithm = APPROACH_TO_ALGORITHM.get(approach)
        if algorithm is None:
            continue
        history = TrainingHistory(
            algorithm=algorithm,
            dataset_filename=Path(csv_path).name,
            status=TrainingStatus.COMPLETED,
            is_production_model=False,
        )
        _persist_history(db, history, metrics, TrainingStatus.COMPLETED, commit=False)
    _mark_production_model(db, TrainingAlgorithm.MINILM, commit=False)
    db.commit()

    _write_comparison_artifacts(results, LIVE_MODEL_NAME)

    return {"results": results, "best_model": LIVE_MODEL_NAME, "best_classical": best_classical}

