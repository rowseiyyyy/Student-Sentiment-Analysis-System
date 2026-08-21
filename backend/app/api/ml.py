import uuid
from pathlib import Path

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
)
from app.services.training import DatasetValidationError, load_and_validate_dataset, run_full_training

router = APIRouter(prefix="/ml", tags=["Machine Learning"])

# Approved active approaches (individual models + the four approved
# ensembles). Legacy SVM / Random Forest / Naive Bayes / BERT rows remain in
# training_history as historical records but are excluded from the active
# comparison, rollback, and download endpoints.
APPROVED_ALGORITHMS = (
    TrainingAlgorithm.XGBOOST,
    TrainingAlgorithm.DEBERTA,
    TrainingAlgorithm.ROBERTA,
    TrainingAlgorithm.ENSEMBLE_XGB_DEBERTA,
    TrainingAlgorithm.ENSEMBLE_DEBERTA_ROBERTA,
    TrainingAlgorithm.ENSEMBLE_ROBERTA_XGB,
    TrainingAlgorithm.ENSEMBLE_XGB_DEBERTA_ROBERTA,
)


@router.post("/dataset/upload", status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .csv files are accepted.")

    settings.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    dest_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest_path = settings.DATASETS_DIR / dest_filename

    content = await file.read()
    with open(dest_path, "wb") as buffer:
        buffer.write(content)

    try:
        df = load_and_validate_dataset(dest_path)
    except DatasetValidationError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return {
        "filename": dest_filename,
        "rows": len(df),
        "categories": sorted(df["category"].unique().tolist()) if "category" in df.columns else [],
        "sentiment_distribution": df["sentiment"].value_counts().to_dict(),
    }


@router.post("/train", response_model=dict)
def train_models(
    payload: TrainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Research-mode: trains SVM + Naive Bayes + Random Forest and
    evaluates BERT on the specified dataset, then automatically promotes
    the best-performing model to production."""
    if not payload.dataset_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="dataset_filename is required. Upload a dataset via /ml/dataset/upload first.",
        )

    csv_path = settings.DATASETS_DIR / payload.dataset_filename
    if not csv_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset file not found.")

    try:
        summary = run_full_training(
            db,
            csv_path,
            n_estimators=payload.n_estimators,
            max_depth=payload.max_depth,
            min_samples_split=payload.min_samples_split,
        )
    except DatasetValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return {
        "message": "Training completed successfully.",
        "best_model": summary["best_model"],
        "metrics": {
            algo: {k: v for k, v in metrics.items() if k not in ("confusion_matrix", "classification_report")}
            for algo, metrics in summary["results"].items()
        },
    }


@router.post("/retrain", response_model=dict)
def retrain_models(
    payload: TrainRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Alias for /train intended for retraining on an updated dataset;
    kept as a distinct endpoint per the API spec for clarity in the
    Admin Panel / audit trail."""
    return train_models(payload, db, current_user)


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

    return {"message": f"Production model rolled back to {target.algorithm.value} (run {target.id})."}


@router.get("/models/{algorithm}/download")
def download_trained_model(algorithm: TrainingAlgorithm, current_user: User = Depends(require_admin)):
    """Expose the approved trained artifacts for download.

    XGBoost serializes to a single ``.pkl`` file. DeBERTa / RoBERTa are
    HuggingFace model directories. Ensembles are reconstructed at runtime
    from their member models and persisted weights, so they are described
    via the deployment metadata rather than a single file.
    """
    if algorithm not in APPROVED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy models (SVM / Random Forest / Naive Bayes / BERT) are no longer downloadable as active artifacts.",
        )

    if algorithm == TrainingAlgorithm.XGBOOST:
        path = Path(settings.XGB_MODEL_PATH)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="XGBoost model artifact not found on disk.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    if algorithm in (TrainingAlgorithm.DEBERTA, TrainingAlgorithm.ROBERTA):
        path = Path(settings.DEBERTA_MODEL_PATH if algorithm == TrainingAlgorithm.DEBERTA else settings.ROBERTA_MODEL_PATH)
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
