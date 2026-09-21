import uuid
import csv
import io
import zipfile
from pathlib import Path

import json

from app.services.training import (
    import_training_results,
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
import zipfile

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

# The ONLY live production model. Imported Colab approaches (SVM, Naive
# Bayes, Logistic Regression) are retained as historical TrainingHistory
# rows — they appear in the model comparison but are excluded from
# production rollback and live inference.
APPROVED_ALGORITHMS = (
    TrainingAlgorithm.MINILM,
)





# Multipart uploads are read into memory, so an unbounded upload will OOM the
# (free-tier, ~512 MB) instance long before any request-size limit is
# enforced. Cap uploads and return a clear, actionable message instead of
# crashing the process.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB hard cap for metrics JSON


async def _read_limited_size(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an uploaded file in bounded chunks, never buffering more than
    ``max_bytes``. Raises 413 with a helpful message if the upload is larger,
    so an oversized (and for this server, unservable) model archive fails
    cleanly instead of exhausting memory."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            await upload.close()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Uploaded file exceeds the {max_bytes // (1024 * 1024)} MB limit. "
                    "Model weight archives are optional â€” import the metrics JSON only "
                    "(the free-tier server cannot load these weights anyway)."
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)



@router.post("/import-results", response_model=ImportResultsResponse)
async def import_results(
    metrics_json: UploadFile = File(...),
    set_production: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Import metrics produced by a Colab training run.

    Only the metrics JSON is accepted; no model weight archives are uploaded.
    The approved set is SVM, Naive Bayes, Logistic Regression and
    Multilingual MiniLM — but only MiniLM is the live model and its weights
    are fetched directly from the private Hugging Face Hub repo at startup.
    """
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

    return ImportResultsResponse(
        message="Import complete.",
        imported_algorithms=outcome["imported_algorithms"],
        production_model=outcome["production_model"],
        recommended_model=outcome.get("recommended_model"),
        artifacts_updated=[],
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
    """Latest run per approach that has training-history rows — the Admin
    Panel comparison table.

    Approaches imported from a Colab metrics JSON (SVM, Naive Bayes,
    Logistic Regression) appear here as research results alongside
    Multilingual MiniLM. ``best_model`` is always
    the LIVE production model (Multilingual MiniLM) — legacy/imported rows are
    display-only and can never serve live inference.
    """
    rows = []
    production_row = (
        db.query(TrainingHistory)
        .filter(TrainingHistory.is_production_model.is_(True))
        .first()
    )
    # Distinct persisted algorithm values (latest run of each), so imported
    # Colab metrics show up even though they are not live models.
    algorithm_values = [
        row[0] for row in db.query(TrainingHistory.algorithm).distinct().all()
    ]
    for value in algorithm_values:
        latest = (
            db.query(TrainingHistory)
            .filter(TrainingHistory.algorithm == value)
            .order_by(TrainingHistory.created_at.desc())
            .first()
        )
        if latest:
            rows.append(ModelComparisonRow(
                algorithm=latest.algorithm.value,
                accuracy=latest.accuracy,
                precision=latest.precision,
                recall=latest.recall,
                f1_score=latest.f1_score,
                training_time_seconds=latest.training_time_seconds,
                inference_time_ms=latest.inference_time_ms,
                is_production_model=latest.is_production_model,
            ))

    return ModelComparisonResponse(
        best_model=production_row.algorithm.value if production_row else None,
        rows=rows,
    )


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
    """Rolls back production to a previous Multilingual MiniLM training run.
    Imported legacy approaches (SVM, Naive Bayes, Logistic Regression) are
    research results only and are NOT eligible
    for live production."""
    target = db.query(TrainingHistory).filter(TrainingHistory.id == training_history_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training history record not found.")

    if target.algorithm not in APPROVED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rollback is only available for Multilingual MiniLM — the only live production model.",
        )

    db.query(TrainingHistory).update({TrainingHistory.is_production_model: False})
    target.is_production_model = True
    db.commit()

    # Keep model_metadata.json's production-model section in sync with this
    # rollback.
    sync_deployment_metadata(db, target.algorithm.value)

    return {"message": f"Production model rolled back to {target.algorithm.value} (run {target.id})."}


@router.get("/models/{algorithm}/download")
def download_trained_model(algorithm: TrainingAlgorithm, current_user: User = Depends(require_admin)):
    """Expose the approved trained artifacts for download.

    The classical research models (SVM / Naive Bayes / Logistic Regression)
    serialize to a single ``.pkl`` (model) plus a paired TF-IDF vectorizer.
    Multilingual MiniLM is an ONNX directory under ``app/ml/minilm_sentiment``.
    """
    if algorithm not in APPROVED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only the approved model set (SVM, Naive Bayes, Logistic Regression, Multilingual MiniLM) is downloadable.",
        )

    CLASSICAL_PATHS = {
        TrainingAlgorithm.SVM: (settings.SVM_MODEL_PATH, settings.SVM_VECTORIZER_PATH),
        TrainingAlgorithm.NAIVE_BAYES: (settings.NAIVE_BAYES_MODEL_PATH, settings.NAIVE_BAYES_VECTORIZER_PATH),
        TrainingAlgorithm.LOGISTIC_REGRESSION: (settings.LOGREG_MODEL_PATH, settings.LOGREG_VECTORIZER_PATH),
    }
    if algorithm in CLASSICAL_PATHS:
        model_path, vectorizer_path = CLASSICAL_PATHS[algorithm]
        if not model_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model artifact not found on disk.")
        return JSONResponse({
            "algorithm": algorithm.value,
            "artifact_type": "joblib",
            "path": str(model_path),
            "vectorizer_path": str(vectorizer_path),
            "note": "Classical models are stored as a Joblib file with a paired TF-IDF vectorizer pickle.",
        })

    # Multilingual MiniLM: ONNX artifacts directory.
    path = Path(settings.MINILM_MODEL_PATH)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MiniLM ONNX artifact directory not found on disk.")
    return JSONResponse({
        "algorithm": algorithm.value,
        "artifact_type": "directory",
        "path": str(path),
        "note": "Multilingual MiniLM is stored as an ONNX directory of artifacts under app/ml/.",
    })
