"""Approved active-model training orchestration for XGBoost, DeBERTa and RoBERTa.

The active research set is intentionally restricted to:
1. XGBoost
2. DeBERTa
3. RoBERTa
4. Weighted soft-voting ensembles of those models:
   - XGBoost + DeBERTa
   - DeBERTa + RoBERTa
   - RoBERTa + XGBoost
   - XGBoost + DeBERTa + RoBERTa

Each ensemble combines per-member probability vectors into one final
probability distribution and prediction. Ensemble member weights are
selected on an untouched validation split and the resulting metrics are
computed on the untouched final test set. The best-performing individual
model *or* ensemble is then selected, its metadata and selected weights are
persisted, and the same selection is used at runtime inference.

Legacy SVM / Naive Bayes / Random Forest / BERT are retained as historical
compatibility records, but no longer participate in the active pipeline.
"""
from __future__ import annotations

import json
import time

import zipfile
import shutil

from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.training_history import TrainingAlgorithm, TrainingHistory, TrainingStatus
from app.services.deberta_service import deberta_service
from app.services.ensembles import (
    ENSEMBLES,
    ensemble_prediction,
    members_of,
    normalize_weights,
    select_weights,
)
from app.services.preprocessing import clean_for_classical
from app.services.roberta_service import roberta_service
from app.services.xgboost_service import CLASS_ORDER, XGBoostService, xgboost_service
from app.utils.logger import logger

REQUIRED_COLUMNS = {"comment", "sentiment"}
VALID_SENTIMENTS = {"Positive", "Neutral", "Negative"}
VALID_CATEGORIES = {"Faculty", "Staff", "Payment", "Facilities"}
RESPONSE_COLUMN_ALIASES = ("comment", "comments", "feedback", "response", "responses", "remarks", "review", "text")
LABEL_COLUMN_ALIASES = ("sentiment", "label")

def import_training_results(
    db: Session,
    metrics_by_algorithm: dict[str, dict],
    dataset_filename: str | None,
    set_production: str | None = None,
) -> dict:
    """Persist metrics produced by an external (Colab) training run as
    TrainingHistory rows, without running any local training.

    `metrics_by_algorithm` maps approach name (e.g. "XGBoost",
    "DeBERTa", "RoBERTa", or an approved ensemble name) to a metrics
    dict shaped like the ones `run_full_training` already produces:
    accuracy, precision, recall, f1_score, macro_f1, weighted_f1,
    confusion_matrix {labels, matrix}, classification_report, and
    optionally training_time_seconds / inference_time_ms / hyperparameters.
    """
    imported: list[str] = []
    unknown_keys: list[str] = []
    for approach_name, metrics in metrics_by_algorithm.items():
        algorithm = APPROACH_TO_ALGORITHM.get(approach_name)
        if algorithm is None:
            # The Colab export can include top-level metadata keys
            # (e.g. "generated_at", dataset info) that are not approaches.
            # Skip them silently instead of failing the whole import.
            unknown_keys.append(approach_name)
            continue

        history = TrainingHistory(
            algorithm=algorithm,
            status=TrainingStatus.RUNNING,
            dataset_filename=dataset_filename or metrics.get("dataset_filename") or "colab_import",
            dataset_size=metrics.get("dataset_size"),
        )
        db.add(history)
        db.commit()
        db.refresh(history)
        _persist_history(db, history, metrics, TrainingStatus.COMPLETED)
        imported.append(approach_name)

    if unknown_keys:
        logger.info(
            f"Ignored non-model keys in metrics JSON: {', '.join(unknown_keys)}"
        )

    if not imported:
        raise DatasetValidationError("Metrics JSON did not contain any recognized approaches.")

    if set_production:
        if set_production not in imported:
            raise DatasetValidationError(
                f"'{set_production}' was requested as production but wasn't in the imported metrics."
            )
        best_algorithm = set_production
    else:
        best_algorithm = max(
            imported,
            key=lambda name: float(metrics_by_algorithm[name].get("weighted_f1", -1.0)),
        )

    _mark_production_model(db, APPROACH_TO_ALGORITHM[best_algorithm])
    serializable = {
        name: {k: v for k, v in metrics_by_algorithm[name].items() if k not in ("validation", "weights")}
        for name in imported
    }
    _write_comparison_artifacts(serializable, best_algorithm)
    sync_deployment_metadata(db, best_algorithm)

    return {"imported_algorithms": imported, "production_model": best_algorithm}


def replace_xgboost_artifacts(model_bytes: bytes, vectorizer_bytes: bytes) -> None:
    settings.ML_DIR.mkdir(parents=True, exist_ok=True)
    Path(settings.XGB_MODEL_PATH).write_bytes(model_bytes)
    Path(settings.XGB_TFIDF_VECTORIZER_PATH).write_bytes(vectorizer_bytes)
    xgboost_service._try_load()  # reload in-place so no restart needed


def replace_transformer_artifacts(zip_bytes: bytes, target_dir: Path) -> None:
    """Extract a zipped HuggingFace model directory (config.json,
    model.safetensors, tokenizer files, etc.) into target_dir,
    overwriting what's there. DeBERTa/RoBERTa services currently load
    once at import time, so a server restart is needed to pick this up
    unless their service classes are extended with a reload method."""
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_extract = target_dir.parent / f"_tmp_extract_{target_dir.name}"
    if tmp_extract.exists():
        shutil.rmtree(tmp_extract)
    tmp_extract.mkdir(parents=True)

    tmp_zip_path = tmp_extract / "upload.zip"
    tmp_zip_path.write_bytes(zip_bytes)
    with zipfile.ZipFile(tmp_zip_path, "r") as zf:
        zf.extractall(tmp_extract)
    tmp_zip_path.unlink()

    for item in target_dir.iterdir():
        if item.is_file():
            item.unlink()
    for item in tmp_extract.iterdir():
        dest = target_dir / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(item), str(dest))
    shutil.rmtree(tmp_extract)


def _normalise_category(value: str) -> str:
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


class DatasetValidationError(Exception):
    pass


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
) -> pd.DataFrame:
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


def _metrics_for_labels(y_true: Iterable[str], y_pred: Iterable[str]) -> dict:
    y_true_arr = np.asarray(list(y_true), dtype=object)
    y_pred_arr = np.asarray(list(y_pred), dtype=object)
    labels = list(CLASS_ORDER)
    report = classification_report(
        y_true_arr,
        y_pred_arr,
        labels=labels,
        target_names=labels,
        output_dict=True,
        zero_division=0,
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


def _split_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    labels = df["sentiment"].tolist()
    idx = np.arange(len(df))
    idx_train_dev, idx_test = train_test_split(
        idx,
        test_size=settings.TEST_SIZE,
        random_state=settings.RANDOM_STATE,
        stratify=labels,
    )
    dev_df = df.iloc[idx_train_dev].reset_index(drop=True)
    test_df = df.iloc[idx_test].reset_index(drop=True)
    dev_labels = dev_df["sentiment"].tolist()
    idx_train, idx_val = train_test_split(
        np.arange(len(dev_df)),
        test_size=0.25,
        random_state=settings.RANDOM_STATE,
        stratify=dev_labels,
    )
    train_df = dev_df.iloc[idx_train].reset_index(drop=True)
    val_df = dev_df.iloc[idx_val].reset_index(drop=True)
    return train_df, val_df, test_df


# Map an approved approach name (individual model or ensemble) to the
# TrainingAlgorithm enum value used for persistence / rollback.
APPROACH_TO_ALGORITHM = {
    "XGBoost": TrainingAlgorithm.XGBOOST,
    "DeBERTa": TrainingAlgorithm.DEBERTA,
    "RoBERTa": TrainingAlgorithm.ROBERTA,
    "XGBoost + DeBERTa": TrainingAlgorithm.ENSEMBLE_XGB_DEBERTA,
    "DeBERTa + RoBERTa": TrainingAlgorithm.ENSEMBLE_DEBERTA_ROBERTA,
    "RoBERTa + XGBoost": TrainingAlgorithm.ENSEMBLE_ROBERTA_XGB,
    "XGBoost + DeBERTa + RoBERTa": TrainingAlgorithm.ENSEMBLE_XGB_DEBERTA_ROBERTA,
}

# Key names used by the Colab dashboard export's ``models`` object, mapped to
# the canonical approved approach names that APPROACH_TO_ALGORITHM and the
# rest of the app recognise.
COLAB_KEY_TO_APPROACH = {
    "xgboost": "XGBoost",
    "deberta": "DeBERTa",
    "roberta": "RoBERTa",
}


def _coerce_model_output(model_name: str, predictions: Any) -> tuple[str, float, list[float]]:
    if isinstance(predictions, tuple) and len(predictions) >= 3:
        label, confidence, probs = predictions
        return str(label), float(confidence), [float(p) for p in probs]
    raise TypeError(f"Unexpected output format from {model_name}: {predictions!r}")


def normalize_metrics_payload(payload: Any) -> tuple[dict[str, dict], str | None]:
    """Accept two metrics-JSON shapes and return ``(flat_metrics, recommended_production)``.

    * **Legacy flat** format: a top-level ``{approach_name: metrics_dict}``
      (e.g. ``{"XGBoost": {...}}``). Passed through unchanged.
    * **Colab dashboard export** (matches ``dashboard_export.json`` from the
      Colab notebook): approaches are nested under a top-level ``"models"``
      object with lowercase keys (``xgboost`` / ``deberta`` / ``roberta``),
      surrounded by metadata keys (``generated_at``, ``label_map``,
      ``recommended_production_model``). Metric names differ too
      (``precision_weighted`` / ``recall_weighted`` / ``per_class`` /
      ``weighted_f1`` vs the legacy ``precision`` / ``recall`` /
      ``classification_report``). This is normalised into the flat shape
      ``import_training_results`` and ``_persist_history`` already consume.

    Identifies the Colab export by the presence of a top-level ``"models"``
    dict; anything else is treated as the legacy flat format.
    """
    if not isinstance(payload, dict):
        raise DatasetValidationError("Metrics JSON must be an object.")
    if not isinstance(payload.get("models"), dict):
        return payload, None

    label_map = payload.get("label_map") or {}
    # Handle both dict (index->name mapping) and list (direct label names) formats
    if isinstance(label_map, dict):
        labels = [str(name) for name in label_map.keys()] if label_map else list(CLASS_ORDER)
    elif isinstance(label_map, list):
        labels = [str(name) for name in label_map] if label_map else list(CLASS_ORDER)
    else:
        labels = list(CLASS_ORDER)

    flat: dict[str, dict] = {}
    for key, model in payload["models"].items():
        approach = COLAB_KEY_TO_APPROACH.get(key)
        if approach is None or not isinstance(model, dict):
            continue
        flat[approach] = _normalize_colab_model(model, labels)

    recommended_raw = payload.get("recommended_production_model")
    recommended = COLAB_KEY_TO_APPROACH.get(recommended_raw) if recommended_raw else None
    return flat, recommended


def _normalize_colab_model(model: dict, label_map: dict | list) -> dict:
    """Map one Colab dashboard model dict onto the metric keys the service
    persists (``_persist_history`` reads accuracy/precision/recall/f1_score/
    macro_f1/weighted_f1/labels/confusion_matrix/classification_report)."""
    # label_map may be a dict (index->name mapping) or an already-resolved list of labels
    if isinstance(label_map, dict):
        labels = [str(n) for n in label_map.keys()] or list(CLASS_ORDER)
    elif isinstance(label_map, list):
        labels = [str(n) for n in label_map] or list(CLASS_ORDER)
    else:
        labels = list(CLASS_ORDER)
    per_class = model.get("per_class") or {}

    report: dict[str, Any] = {"accuracy": model.get("accuracy")}
    macro_vals = []
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
        # Colab exports do not carry a raw confusion-matrix; Persist what the
        # export included, if any (else the caller's _persist_history writes a
        # placeholder).
        "confusion_matrix": model.get("confusion_matrix"),
        "classification_report": report,
        "training_time_seconds": model.get("training_time_seconds"),
        "inference_time_ms": model.get("inference_time_ms"),
        "memory_usage_mb": model.get("memory_usage_mb"),
        "hyperparameters": model.get("hyperparameters"),
    }


def _persist_history(db: Session, history: TrainingHistory, metrics: dict, status: TrainingStatus) -> None:
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
    db.commit()


def _mark_production_model(db: Session, algorithm: TrainingAlgorithm) -> None:
    db.query(TrainingHistory).update({TrainingHistory.is_production_model: False})
    latest = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.algorithm == algorithm)
        .order_by(TrainingHistory.created_at.desc())
        .first()
    )
    if latest:
        latest.is_production_model = True
    db.commit()


def _write_comparison_artifacts(results: dict, best_algorithm: str, selection_metric: str = "weighted_f1") -> None:
    settings.ML_DIR.mkdir(parents=True, exist_ok=True)
    best_metrics = results.get(best_algorithm, {})
    approach_type = "ensemble" if best_algorithm in ENSEMBLES else "single"
    selection_score = float(best_metrics.get(selection_metric, best_metrics.get("weighted_f1", 0.0)))

    metadata: dict = {
        "production_model": best_algorithm,
        "approach_type": approach_type,
        "selection_metric": selection_metric,
        "selection_score": selection_score,
        "models": results,
    }
    if approach_type == "ensemble":
        metadata["ensemble_members"] = members_of(best_algorithm)
        # Persist the weights actually selected during training so runtime
        # inference can reconstruct this ensemble without consulting
        # configuration defaults.
        metadata["ensemble_weights"] = best_metrics.get("weights", {})

    with open(settings.COMPARISON_RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"best_model": best_algorithm, "rows": results}, fh, indent=2)
    with open(settings.MODEL_METADATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)


def sync_deployment_metadata(db: Session, algorithm_name: str) -> None:
    """Rewrite the ``production_model`` section of ``model_metadata.json`` to
    match ``algorithm_name``.

    ``model_metadata.json`` is normally written once per training run, for
    whichever approach scored best (see ``_write_comparison_artifacts``).
    If an admin later rolls back production to a *different* approved
    approach via ``/ml/rollback``, that file is otherwise never updated,
    which left runtime inference (``get_deployment_config`` in
    ``app/services/prediction.py``) reconstructing ensembles using the
    *previous* best approach's stale member list and weights. This function
    must be called any time ``TrainingHistory.is_production_model`` changes
    outside of ``run_full_training`` itself (i.e. on rollback), using each
    ensemble's own persisted weights (stored in ``TrainingHistory.hyperparameters``
    at training time) rather than falling back to configuration defaults.
    """
    settings.ML_DIR.mkdir(parents=True, exist_ok=True)

    metadata: dict = {}
    if settings.MODEL_METADATA_PATH.exists():
        try:
            with open(settings.MODEL_METADATA_PATH, encoding="utf-8") as fh:
                metadata = json.load(fh)
        except (json.JSONDecodeError, OSError):
            metadata = {}

    metadata["production_model"] = algorithm_name

    if algorithm_name in ENSEMBLES:
        history_algorithm = APPROACH_TO_ALGORITHM.get(algorithm_name)
        latest = (
            db.query(TrainingHistory)
            .filter(TrainingHistory.algorithm == history_algorithm)
            .order_by(TrainingHistory.created_at.desc())
            .first()
        )
        members = members_of(algorithm_name)
        trained_weights = {}
        if latest is not None and latest.hyperparameters:
            trained_weights = latest.hyperparameters.get("weights") or {}
        metadata["approach_type"] = "ensemble"
        metadata["ensemble_members"] = members
        # Always derived from *this* approach's own persisted weights; never
        # silently reused from whatever ensemble was previously in production.
        metadata["ensemble_weights"] = normalize_weights(members, trained_weights)
    else:
        metadata["approach_type"] = "single"
        metadata.pop("ensemble_members", None)
        metadata.pop("ensemble_weights", None)

    with open(settings.MODEL_METADATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)


def run_full_training(
    db: Session,
    csv_path: Path,
    n_estimators: int = 300,
    max_depth: int | None = None,
    min_samples_split: int = 2,
    evaluate_bert: bool = True,
) -> dict:
    """Train and evaluate the approved XGBoost/DeBERTa/RoBERTa active pipeline.

    The same untouched final test set must be used across all three approved
    models; no final-test observations are used for model-selection or ensemble
    weight optimisation.
    """
    df = load_and_validate_dataset(csv_path)
    train_df, val_df, test_df = _split_dataset(df)

    train_texts = train_df["comment"].tolist()
    train_labels = train_df["sentiment"].tolist()
    val_texts = val_df["comment"].tolist()
    val_labels = val_df["sentiment"].tolist()
    test_texts = test_df["comment"].tolist()
    test_labels = test_df["sentiment"].tolist()

    run_id = str(time.time_ns())
    results: dict[str, dict] = {}
    test_model_probabilities: dict[str, list[np.ndarray]] = {"XGBoost": [], "DeBERTa": [], "RoBERTa": []}
    val_model_probabilities: dict[str, list[np.ndarray]] = {"XGBoost": [], "DeBERTa": [], "RoBERTa": []}

    xgb_history = TrainingHistory(
        algorithm=TrainingAlgorithm.XGBOOST,
        status=TrainingStatus.RUNNING,
        dataset_filename=csv_path.name,
        dataset_size=len(df),
    )
    db.add(xgb_history); db.commit(); db.refresh(xgb_history)
    try:
        xgb_metrics = xgboost_service.train_on_split(train_texts, train_labels, val_texts, val_labels, test_texts, test_labels)
        xgb_metrics["training_time_seconds"] = float(xgb_metrics.get("training_time_seconds", 0.0))
        xgb_metrics["inference_time_ms"] = float(xgb_metrics.get("inference_time_ms", 0.0))
        xgb_metrics["memory_usage_mb"] = float(xgb_metrics.get("memory_usage_mb", 0.0))
        xgb_metrics["dataset_size"] = len(df)
        xgb_metrics["split_sizes"] = {"train": len(train_texts), "validation": len(val_texts), "test": len(test_texts)}
        xgb_metrics["hyperparameters"] = {"n_estimators": settings.XGB_N_ESTIMATORS, "max_depth": settings.XGB_MAX_DEPTH, "learning_rate": settings.XGB_LEARNING_RATE}
        _persist_history(db, xgb_history, xgb_metrics, TrainingStatus.COMPLETED)
        results["XGBoost"] = xgb_metrics
        for text in test_texts:
            _, _, probs = xgboost_service.predict(text)
            test_model_probabilities["XGBoost"].append(np.asarray(probs, dtype=float))
        for text in val_texts:
            _, _, probs = xgboost_service.predict(text)
            val_model_probabilities["XGBoost"].append(np.asarray(probs, dtype=float))
    except Exception as exc:  # noqa: BLE001
        logger.warning("XGBoost training failed: %s", exc)
        xgb_history.status = TrainingStatus.FAILED; xgb_history.notes = str(exc); db.commit()

    deberta_history = TrainingHistory(
        algorithm=TrainingAlgorithm.DEBERTA,
        status=TrainingStatus.RUNNING,
        dataset_filename=csv_path.name,
        dataset_size=len(df),
    )
    db.add(deberta_history); db.commit(); db.refresh(deberta_history)
    try:
        metrics = deberta_service.fine_tune(
            train_texts=train_texts,
            train_labels=train_labels,
            val_texts=val_texts,
            val_labels=val_labels,
            output_dir=settings.DEBERTA_MODEL_PATH / f"run_{run_id}",
            epochs=settings.DEBERTA_EPOCHS,
            learning_rate=settings.DEBERTA_LEARNING_RATE,
            batch_size=settings.DEBERTA_BATCH_SIZE,
            max_length=settings.DEBERTA_MAX_SEQ_LENGTH,
            seed=settings.RANDOM_STATE,
        )
        y_pred = []
        for text in test_texts:
            label, _, probs = deberta_service.predict(text)
            y_pred.append(label)
            test_model_probabilities["DeBERTa"].append(np.asarray(probs, dtype=float))
        for text in val_texts:
            _, _, probs = deberta_service.predict(text)
            val_model_probabilities["DeBERTa"].append(np.asarray(probs, dtype=float))
        debert_metrics = _metrics_for_labels(test_labels, y_pred)
        debert_metrics["training_time_seconds"] = float(metrics.get("training_time_seconds", 0.0))
        debert_metrics["inference_time_ms"] = float(metrics.get("inference_time_ms", 0.0))
        debert_metrics["memory_usage_mb"] = float(metrics.get("memory_usage_mb", 0.0))
        debert_metrics["dataset_size"] = len(df)
        debert_metrics["split_sizes"] = {"train": len(train_texts), "validation": len(val_texts), "test": len(test_texts)}
        debert_metrics["validation"] = _metrics_for_labels(val_labels, [deberta_service.predict(text)[0] for text in val_texts])
        debert_metrics["hyperparameters"] = {"epochs": settings.DEBERTA_EPOCHS, "learning_rate": settings.DEBERTA_LEARNING_RATE, "batch_size": settings.DEBERTA_BATCH_SIZE, "max_seq_length": settings.DEBERTA_MAX_SEQ_LENGTH, "seed": settings.RANDOM_STATE, "checkpoint": settings.DEBERTA_MODEL_NAME}
        _persist_history(db, deberta_history, debert_metrics, TrainingStatus.COMPLETED)
        results["DeBERTa"] = debert_metrics
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"DeBERTa training failed: {exc}")
        deberta_history.status = TrainingStatus.FAILED; deberta_history.notes = str(exc); db.commit()

    roberta_history = TrainingHistory(
        algorithm=TrainingAlgorithm.ROBERTA,
        status=TrainingStatus.RUNNING,
        dataset_filename=csv_path.name,
        dataset_size=len(df),
    )
    db.add(roberta_history); db.commit(); db.refresh(roberta_history)
    try:
        metrics = roberta_service.fine_tune(
            train_texts=train_texts,
            train_labels=train_labels,
            val_texts=val_texts,
            val_labels=val_labels,
            output_dir=settings.ROBERTA_MODEL_PATH / f"run_{run_id}",
            epochs=settings.DEBERTA_EPOCHS,
            learning_rate=settings.DEBERTA_LEARNING_RATE,
            batch_size=settings.DEBERTA_BATCH_SIZE,
            max_length=settings.DEBERTA_MAX_SEQ_LENGTH,
            seed=settings.RANDOM_STATE,
        )
        y_pred = []
        for text in test_texts:
            label, _, probs = roberta_service.predict(text)
            y_pred.append(label)
            test_model_probabilities["RoBERTa"].append(np.asarray(probs, dtype=float))
        for text in val_texts:
            _, _, probs = roberta_service.predict(text)
            val_model_probabilities["RoBERTa"].append(np.asarray(probs, dtype=float))
        roberta_metrics = _metrics_for_labels(test_labels, y_pred)
        roberta_metrics["training_time_seconds"] = float(metrics.get("training_time_seconds", 0.0))
        roberta_metrics["inference_time_ms"] = float(metrics.get("inference_time_ms", 0.0))
        roberta_metrics["memory_usage_mb"] = float(metrics.get("memory_usage_mb", 0.0))
        roberta_metrics["dataset_size"] = len(df)
        roberta_metrics["split_sizes"] = {"train": len(train_texts), "validation": len(val_texts), "test": len(test_texts)}
        roberta_metrics["validation"] = _metrics_for_labels(val_labels, [roberta_service.predict(text)[0] for text in val_texts])
        roberta_metrics["hyperparameters"] = {"epochs": settings.DEBERTA_EPOCHS, "learning_rate": settings.DEBERTA_LEARNING_RATE, "batch_size": settings.DEBERTA_BATCH_SIZE, "max_seq_length": settings.DEBERTA_MAX_SEQ_LENGTH, "seed": settings.RANDOM_STATE, "checkpoint": settings.ROBERTA_MODEL_NAME}
        _persist_history(db, roberta_history, roberta_metrics, TrainingStatus.COMPLETED)
        results["RoBERTa"] = roberta_metrics
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"RoBERTa training failed: {exc}")
        roberta_history.status = TrainingStatus.FAILED; roberta_history.notes = str(exc); db.commit()

    if not test_model_probabilities["XGBoost"] or not test_model_probabilities["DeBERTa"] or not test_model_probabilities["RoBERTa"]:
        raise RuntimeError("The active research pipeline requires successful XGBoost, DeBERTa, and RoBERTa training to complete.")

    # Build all four approved ensembles. Member weights are selected on the
    # untouched validation split; final metrics are computed on the untouched
    # test set so no test observation influences selection.
    available_members: set[str] = set()
    for name in ("XGBoost", "DeBERTa", "RoBERTa"):
        if test_model_probabilities[name]:
            available_members.add(name)

    for ensemble_name, members in ENSEMBLES.items():
        if not set(members).issubset(available_members):
            logger.warning("Skipping ensemble %s: not all member models are available.", ensemble_name)
            continue

        weights = select_weights(ensemble_name, val_model_probabilities, val_labels)
        weights = normalize_weights(members, weights)

        ensemble_labels = ensemble_prediction(ensemble_name, test_model_probabilities, weights)
        if len(ensemble_labels) != len(test_labels):
            raise RuntimeError(
                f"Ensemble '{ensemble_name}' output length mismatch on the untouched final test set."
            )

        ensemble_metrics = _metrics_for_labels(test_labels, ensemble_labels)
        ensemble_metrics["weights"] = weights
        ensemble_metrics["members"] = members
        ensemble_metrics["validation"] = _metrics_for_labels(
            val_labels,
            ensemble_prediction(ensemble_name, val_model_probabilities, weights),
        )
        ensemble_metrics["hyperparameters"] = {
            "members": members,
            "weights": weights,
            "selection": "validation macro-F1",
        }
        ensemble_metrics["split_sizes"] = {
            "train": len(train_texts),
            "validation": len(val_texts),
            "test": len(test_texts),
        }
        results[ensemble_name] = ensemble_metrics

        ensemble_history = TrainingHistory(
            algorithm=APPROACH_TO_ALGORITHM[ensemble_name],
            status=TrainingStatus.RUNNING,
            dataset_filename=csv_path.name,
            dataset_size=len(df),
        )
        db.add(ensemble_history); db.commit(); db.refresh(ensemble_history)
        _persist_history(db, ensemble_history, ensemble_metrics, TrainingStatus.COMPLETED)

    def _validation_score(metrics: dict) -> float:
        """Model/ensemble selection must use validation performance, never
        the held-out test set, so the final reported test metrics remain an
        unbiased estimate of generalization for whichever approach wins."""
        validation = metrics.get("validation") or {}
        return float(validation.get("weighted_f1", -1.0))

    best_algorithm = max(results, key=lambda key: _validation_score(results[key]))

    _mark_production_model(db, APPROACH_TO_ALGORITHM[best_algorithm])
    serializable = {
        name: {k: v for k, v in metrics.items() if k not in ("validation", "weights")}
        for name, metrics in results.items()
    }
    _write_comparison_artifacts(serializable, best_algorithm)
    selected_weights = results[best_algorithm].get("weights", {}) if best_algorithm in ENSEMBLES else {}
    return {
        "results": results,
        "best_model": best_algorithm,
        "ensemble_weights": selected_weights,
        "approach_type": "ensemble" if best_algorithm in ENSEMBLES else "single",
        "ensemble_name": best_algorithm if best_algorithm in ENSEMBLES else None,
    }