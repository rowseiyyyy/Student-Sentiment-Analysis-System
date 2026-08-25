"""
API router for bulk-importing compiled student evaluation data from
.xlsx, .xls, and .csv files (e.g. Google Forms exports).

All endpoints in this router require administrator privileges.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.evaluation import EvaluationCategory
from app.models.user import User
from app.schemas.evaluation import ImportResultResponse, ImportRowError
from app.services.import_service import (
    ImportValidationError,
    get_extension,
    parse_uploaded_file,
    process_imported_evaluations,
    validate_imported_data,
)
from app.utils.logger import logger

router = APIRouter(prefix="/imports", tags=["Data Import"])


@router.post("/evaluations", response_model=ImportResultResponse, status_code=status.HTTP_201_CREATED)
async def import_evaluations(
    file: UploadFile = File(...),
    category: EvaluationCategory = Form(
        ...,
        description="The evaluation form this file came from — Faculty, Staff, Facilities, or Payment. "
                    "Applied to every row in the file.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Upload a compiled student evaluation file (.xlsx, .xls, .csv) — one
    file per category (Faculty / Staff / Facilities / Payment), matching
    how the source Google Forms are structured — and bulk-import every
    valid row as a full Evaluation record: Student ID/Course/Year Level
    (if present, looked up or created as a User, same as a live
    submission), Evaluatee, Likert ratings, and the open-ended comment.

    Do NOT include a Sentiment column — sentiment is always computed
    fresh here via the live XGBoost + DeBERTa + RoBERTa pipeline, the
    same as a normal student submission.

    Returns a summary with the number of rows imported, failed, and
    per-row error details for any rows that could not be processed.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file was uploaded.",
        )

    try:
        ext = get_extension(file.filename)
    except ImportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)
    except OSError as exc:
        logger.error(f"Failed to save uploaded file: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file. Please try again.",
        )

    try:
        rows = parse_uploaded_file(tmp_path)
    except ImportValidationError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    try:
        clean_rows, error_rows = validate_imported_data(rows, category=category.value)
    except ImportValidationError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # NOTE: no user_id is passed here anymore — each row is attributed
    # to its OWN student_id (if the file included one) or left
    # anonymous, never to the importing admin.
    result = process_imported_evaluations(
        db=db,
        clean_rows=clean_rows,
        run_prediction=True,
    )

    tmp_path.unlink(missing_ok=True)

    all_errors = [
        ImportRowError(
            row=err["_row"],
            comment=err.get("_preview", ""),
            errors=err["_errors"],
        )
        for err in error_rows
    ]
    all_errors.extend(
        ImportRowError(row=e["row"], comment=e["comment"], errors=[e["error"]])
        for e in result.errors
    )

    return ImportResultResponse(
        total_rows=result.total_rows + len(error_rows),
        imported=result.imported,
        failed=result.failed + len(error_rows),
        errors=all_errors,
    )