"""
API router for bulk-importing compiled student evaluation data from
.xlsx, .xls, and .csv files.

All endpoints in this router require administrator privileges.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Upload a compiled student evaluation file (.xlsx, .xls, .csv) and
    bulk-import all valid rows as Evaluation records.

    The file should contain at minimum a **Comment** (or Feedback /
    Suggestion) column and a **Category** (or Aspect / Area) column.
    A Timestamp column is optional and will be parsed when present.

    For each valid row a full sentiment prediction (SVM, Random Forest,
    BERT) is run and stored alongside the evaluation.

    Returns a summary with the number of rows imported, failed, and
    per-row error details for any rows that could not be processed.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file was uploaded.",
        )

    # Validate file extension
    try:
        ext = get_extension(file.filename)
    except ImportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Save uploaded file to a temporary location
    try:
        suffix = ext  # .xlsx, .xls, or .csv
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
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
        # Step 1: Parse raw rows from the file
        rows = parse_uploaded_file(tmp_path)
    except ImportValidationError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Step 2: Validate rows (column detection + content validation)
    try:
        clean_rows, error_rows = validate_imported_data(rows)
    except ImportValidationError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Step 3: Process valid rows into the database
    user_id = current_user.id
    result = process_imported_evaluations(
        db=db,
        clean_rows=clean_rows,
        user_id=user_id,
        run_prediction=True,
    )

    # Clean up the temporary file
    tmp_path.unlink(missing_ok=True)

    # Combine validation errors with processing errors
    all_errors = []
    for err in error_rows:
        all_errors.append(
            ImportRowError(
                row=err.get("_row", 0),
                comment=err.get(next(iter(err.keys() - {"_row", "_errors"}), ""), "")[:100],
                errors=err.get("_errors", []),
            )
        )
    for proc_err in result.errors:
        all_errors.append(
            ImportRowError(
                row=proc_err["row"],
                comment=proc_err["comment"][:100],
                errors=[proc_err["error"]],
            )
        )

    return ImportResultResponse(
        total_rows=result.total_rows + len(error_rows),
        imported=result.imported,
        failed=result.failed + len(error_rows),
        errors=all_errors,
    )

