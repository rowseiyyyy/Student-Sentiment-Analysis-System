import uuid
import csv
import io
import zipfile
from pathlib import Path

import json

from app.services.training import (
    
    import_training_results,
    replace_transformer_artifacts,
    replace_xgboost_artifacts,
)

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.training_history import TrainingAlgorithm, TrainingHistory
from app.models.user import User
from app.schemas.ml import (
    ClassificationReportResponse,
    ConfusionMatrixResponse,
    ModelComparisonResponse,
    ModelComparisonRow,
    TrainingHistoryOut,
    TrainRequest,
    ImportResultsResponse
)
from app.services.training import (
    DatasetValidationError,
    load_and_validate_dataset,
    normalize_metrics_payload,
    run_full_training,
    sync_deployment_metadata,
)

router = APIRouter(prefix="/ml", tags=["Machine Learning"])


@router.post("/dataset/upload", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Compatibility endpoint expected by older admin tests.

    The production workflow uses Colab-generated datasets and imports them via
    the metrics-import endpoints, but this route is kept for legacy admin tools
    and local validation scripts. It accepts a CSV file, counts the rows, and
    returns an upload confirmation without mutating the database.
    """
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file was uploaded.")

    if Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV upload is supported.")

    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CSV file is missing a header row.")

    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CSV file contains no data rows.")

    return {"rows": len(rows), "columns": reader.fieldnames, "message": "Dataset uploaded successfully."}

# Approved active approaches (3 individual models + 1 approved ensemble).
# This is the strict, system-wide whitelist: the platform may ONLY use
# XGBoost (TF-DF), mDeBERTa, XLM-RoBERTa, and the "mDeBERTa + XLM-RoBERTa"
# ensemble. Legacy
# models (SVM / Random Forest / Naive Bayes / BERT) and the other ensemble
# combinations are retained only as historical training_history rows and are
# excluded from performance, rollback, confusion-matrix, and download
# endpoints.
APPROVED_ALGORITHMS = (
    TrainingAlgorithm.XGBOOST_TFDF,
    TrainingAlgorithm.MDEBERTA,
    TrainingAlgorithm.XLM_ROBERTA,
    TrainingAlgorithm.ENSEMBLE_MDEBERTA_XLM,
)



@router.post("/import-results", response_model=ImportResultsResponse)
async def import_results(
    metrics_json: UploadFile = File(...),
    xgb_model: UploadFile | None = File(None),
    xgb_vectorizer: UploadFile | None = File(None),
    deberta_archive: UploadFile | None = File(None),
    roberta_archive: UploadFile | None = File(None),
    set_production: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Import metrics (and optionally model weights) produced by a Colab
    training run, in place of local /ml/train."""
    try:
        raw = await metrics_json.read()
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid metrics JSON: {exc}")

    try:
        metrics_by_algorithm, recommended = normalize_metrics_payload(payload)
        if not set_production and recommended:
            set_production = recommended
        outcome = import_training_results(
            db,
            metrics_by_algorithm=metrics_by_algorithm,
            dataset_filename=None,
            set_production=set_production,
        )
    except DatasetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    artifacts_updated: list[str] = []
    if xgb_model and xgb_vectorizer:
        try:
            replace_xgboost_artifacts(await xgb_model.read(), await xgb_vectorizer.read())
        except DatasetValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        artifacts_updated.append("XGBoost (TF-DF)")
    if deberta_archive:
        try:
            replace_transformer_artifacts(await deberta_archive.read(), Path(settings.MDEBERTA_MODEL_PATH))
        except (DatasetValidationError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid DeBERTa archive: {exc}") from exc
        artifacts_updated.append("mDeBERTa")
    if roberta_archive:
        try:
            replace_transformer_artifacts(await roberta_archive.read(), Path(settings.XLM_ROBERTA_MODEL_PATH))
        except (DatasetValidationError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid RoBERTa archive: {exc}") from exc
        artifacts_updated.append("XLM-RoBERTa")

    return ImportResultsResponse(
        message="Import complete.",
        imported_algorithms=outcome["imported_algorithms"],
        production_model=outcome["production_model"],
        artifacts_updated=artifacts_updated,
    )


@router.get("/models", response_model=list[TrainingHistoryOut])
def list_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    algorithm: TrainingAlgorithm | None = None,
):
    query = db.query(TrainingHistory).order_by(TrainingHistory.created_at.desc())
    if algorithm is not None:
        query = query.filter(TrainingHistory.algorithm == algorithm)
    return query.all()


@router.get("/performance", response_model=ModelComparisonResponse)
def get_model_performance(db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Latest run per approved approach, i.e. the Admin Panel comparison
    table. Only approved models and ensembles are compared; legacy rows are
    excluded from the active comparison."""
    rows = []
    best_model = None
    for algo in APPROVED_ALGORITHMS:
        latest = (
            db.query(TrainingHistory)
            .filter(TrainingHistory.algorithm == algo)
            .order_by(TrainingHistory.created_at.desc())
            .first()
        )
        if latest:
            rows.append(ModelComparisonRow(
                algorithm=algo.value,
                accuracy=latest.accuracy,
                precision=latest.precision,
                recall=latest.recall,
                f1_score=latest.f1_score,
                training_time_seconds=latest.training_time_seconds,
                inference_time_ms=latest.inference_time_ms,
                is_production_model=latest.is_production_model,
            ))
            if latest.is_production_model:
                best_model = algo.value

    return ModelComparisonResponse(best_model=best_model, rows=rows)


@router.get("/confusion-matrix", response_model=ConfusionMatrixResponse)
def get_confusion_matrix(
    algorithm: TrainingAlgorithm,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    latest = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.algorithm == algorithm)
        .order_by(TrainingHistory.created_at.desc())
        .first()
    )
    if not latest or not latest.confusion_matrix:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No training run found for this model.")

    return ConfusionMatrixResponse(
        algorithm=algorithm.value,
        labels=latest.confusion_matrix.get("labels", []),
        matrix=latest.confusion_matrix.get("matrix", []),
    )


@router.get("/classification-report", response_model=ClassificationReportResponse)
def get_classification_report(
    algorithm: TrainingAlgorithm,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    latest = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.algorithm == algorithm)
        .order_by(TrainingHistory.created_at.desc())
        .first()
    )
    if not latest or not latest.classification_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No training run found for this model.")

    return ClassificationReportResponse(algorithm=algorithm.value, report=latest.classification_report)


@router.post("/rollback", response_model=dict)
def rollback_production_model(
    training_history_id: str = Query(..., description="TrainingHistory.id to promote to production"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Rolls back the production approach to a previous approved training
    run (XGBoost / DeBERTa / RoBERTa or one of the four approved ensembles).
    Legacy approaches are no longer eligible for active rollback."""
    target = db.query(TrainingHistory).filter(TrainingHistory.id == training_history_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training history record not found.")

    if target.algorithm not in APPROVED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rollback is only available for approved approaches (XGBoost, DeBERTa, RoBERTa, and the approved ensembles).",
        )

    db.query(TrainingHistory).update({TrainingHistory.is_production_model: False})
    target.is_production_model = True
    db.commit()

    # Keep model_metadata.json's production-model section (used to
    # reconstruct ensembles at inference time) in sync with this rollback,
    # using the rolled-back approach's own trained weights.
    sync_deployment_metadata(db, target.algorithm.value)

    return {"message": f"Production model rolled back to {target.algorithm.value} (run {target.id})."}


@router.get("/models/{algorithm}/download")
def download_trained_model(algorithm: TrainingAlgorithm, current_user: User = Depends(require_admin)):
    """Expose the approved trained artifacts for download.

    XGBoost serializes to a single ``.pkl`` or ``.joblib`` file. DeBERTa / RoBERTa are
    HuggingFace model directories. Ensembles are reconstructed at runtime
    from their member models and persisted weights, so they are described
    via the deployment metadata rather than a single file.
    """
    if algorithm not in APPROVED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy models (SVM / Random Forest / Naive Bayes / BERT) are no longer downloadable as active artifacts.",
        )

    if algorithm == TrainingAlgorithm.XGBOOST_TFDF:
        path = Path(settings.XGB_MODEL_PATH)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="XGBoost model artifact not found on disk.")
        return JSONResponse({
            "algorithm": algorithm.value,
            "artifact_type": "joblib" if path.is_file() else "directory",
            "path": str(path),
            "note": "XGBoost models are stored as a Joblib file; legacy TF-DF SavedModel directories are also supported.",
        })

    if algorithm in (TrainingAlgorithm.MDEBERTA, TrainingAlgorithm.XLM_ROBERTA):
        path = Path(settings.MDEBERTA_MODEL_PATH if algorithm == TrainingAlgorithm.MDEBERTA else settings.XLM_ROBERTA_MODEL_PATH)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transformer model directory not found on disk.")
        return JSONResponse({
            "algorithm": algorithm.value,
            "artifact_type": "directory",
            "path": str(path),
            "note": "Transformer models are stored as a directory of HuggingFace artifacts under app/ml/.",
        })

    # Ensemble approaches: reconstructed at runtime from members + weights.
    return JSONResponse({
        "algorithm": algorithm.value,
        "artifact_type": "ensemble",
        "note": "Ensembles are reconstructed at runtime from their member models and the persisted ensemble weights.",
        "deployment_metadata_path": str(settings.MODEL_METADATA_PATH),
    })