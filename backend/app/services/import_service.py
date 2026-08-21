"""
File import service for bulk-uploading compiled student evaluation data
from Excel (.xlsx, .xls) and CSV (.csv) files exported from Google Forms,
Microsoft Forms, or the institution's evaluation system.

Workflow
--------
1. parse_uploaded_file  — reads the raw file into a list of dicts (rows).
2. validate_imported_data  — checks column presence, valid categories,
   non-empty comments, and returns clean rows + per-row errors.
3. process_imported_evaluations  — bulk-inserts valid Evaluation records
   (and optionally runs the full prediction pipeline on each).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy.orm import Session

from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction
from app.services.prediction import run_prediction_pipeline
from app.services.preprocessing import clean_for_classical
from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_COLUMN_MAP = {
    "category": [
        "category", "categories", "aspect", "area", "type",
        "evaluation category", "evaluation aspect",
    ],
    "comment": [
        "comment", "comments", "feedback", "suggestion", "suggestions",
        "remarks", "review", "message", "text", "response",
        "your feedback", "your comments", "your suggestions",
        "open-ended feedback", "student feedback",
    ],
}

TIMESTAMP_KEYWORDS = [
    "timestamp", "date", "time", "submitted", "submission date",
    "submission time", "datetime", "date submitted",
]

VALID_CATEGORIES = {c.value.lower() for c in EvaluationCategory}

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ImportValidationError(Exception):
    """Raised when the uploaded file fails structural validation."""


class ImportRowError(Exception):
    """Raised when an individual row fails validation."""


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


class ImportResult:
    """Holds a summary of the import operation."""

    def __init__(self) -> None:
        self.total_rows: int = 0
        self.imported: int = 0
        self.failed: int = 0
        self.errors: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "imported": self.imported,
            "failed": self.failed,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Column detection helpers
# ---------------------------------------------------------------------------


def _normalise_header(name: str) -> str:
    """Lower-case, strip whitespace, and collapse multiple spaces."""
    return " ".join(name.strip().lower().split())


def _detect_column(headers: list[str], keywords: list[str]) -> int | None:
    """Return the index of the first header that contains any of the
    given *keywords* (case-insensitive, partial match)."""
    normalised = [_normalise_header(h) for h in headers]
    for kw in keywords:
        kw_norm = _normalise_header(kw)
        for idx, hdr in enumerate(normalised):
            if kw_norm in hdr or hdr in kw_norm:
                return idx
    return None


def _resolve_column_map(
    headers: list[str],
) -> dict[str, int]:
    """Return ``{'category': <index>, 'comment': <index>}``.

    Raises ``ImportValidationError`` if either column cannot be detected.
    """
    cat_idx = _detect_column(headers, REQUIRED_COLUMN_MAP["category"])
    com_idx = _detect_column(headers, REQUIRED_COLUMN_MAP["comment"])
    ts_idx = _detect_column(headers, TIMESTAMP_KEYWORDS)

    if cat_idx is None and len(headers) >= 2:
        # Fallback: assume the second column is the category
        cat_idx = 1

    if com_idx is None and len(headers) >= 3:
        # Fallback: assume the third (or last) column is the comment
        com_idx = 2 if cat_idx != 2 else 3
    elif com_idx is None and len(headers) >= 1:
        # If only one column, assume it is the comment
        com_idx = 0

    if cat_idx is None:
        raise ImportValidationError(
            "Could not detect a 'Category' column. Expected column names "
            f"containing one of: {REQUIRED_COLUMN_MAP['category']}"
        )
    if com_idx is None:
        raise ImportValidationError(
            "Could not detect a 'Comment' column. Expected column names "
            f"containing one of: {REQUIRED_COLUMN_MAP['comment']}"
        )

    return {"category": cat_idx, "comment": com_idx, "timestamp": ts_idx}


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


def get_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise ImportValidationError(
            f"Unsupported file format '{ext}'. "
            f"Supported formats: {', '.join(_SUPPORTED_EXTENSIONS)}"
        )
    return ext


def _read_csv_rows(file_path: Path) -> list[list[str]]:
    """Read a CSV file and return rows as lists of strings."""
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        rows = []
        for row in reader:
            rows.append([cell.strip() for cell in row])
    return rows


def _read_excel_rows(file_path: Path) -> list[list[str]]:
    """Read an Excel file (xlsx/xls) and return rows as lists of strings."""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    rows: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(cell).strip() if cell is not None else "" for cell in row])
    wb.close()
    return rows


def parse_uploaded_file(file_path: Path) -> list[dict[str, Any]]:
    """Parse an uploaded file into a list of dictionaries keyed by the
    original column headers.

    Parameters
    ----------
    file_path : Path
        Path to the uploaded file.

    Returns
    -------
    list[dict[str, Any]]
        Each dict represents a data row, keyed by the column header.

    Raises
    ------
    ImportValidationError
        If the file cannot be read or has no data rows.
    """
    ext = file_path.suffix.lower()
    logger.info(f"Parsing uploaded file: {file_path.name} (format: {ext})")

    if ext == ".csv":
        raw_rows = _read_csv_rows(file_path)
    else:  # .xlsx, .xls
        raw_rows = _read_excel_rows(file_path)

    if not raw_rows:
        raise ImportValidationError("The uploaded file appears to be empty.")

    headers = raw_rows[0]
    data_rows = raw_rows[1:]

    if not data_rows:
        raise ImportValidationError("The uploaded file contains a header row but no data rows.")

    # Build result
    result = []
    for row in data_rows:
        # Pad short rows with empty strings
        while len(row) < len(headers):
            row.append("")
        result.append(dict(zip(headers, row)))

    logger.info(f"Parsed {len(result)} rows from {file_path.name}")
    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _normalise_category(value: str) -> str:
    """Try to match a raw category value to one of the official
    ``EvaluationCategory`` values."""
    val = value.strip().lower()
    for cat in EvaluationCategory:
        if cat.value.lower() == val:
            return cat.value
        # Fuzzy: e.g. "instructor" -> "Faculty", " Admin " -> "Staff"
    # Manual common mappings
    aliases = {
        "instructor": "Faculty",
        "teacher": "Faculty",
        "professor": "Faculty",
        "faculty member": "Faculty",
        "admin": "Staff",
        "administration": "Staff",
        "employee": "Staff",
        "personnel": "Staff",
        "payment": "Payment",
        "billing": "Payment",
        "finance": "Payment",
        "facility": "Facilities",
        "facilities": "Facilities",
        "campus": "Facilities",
        "infrastructure": "Facilities",
    }
    return aliases.get(val, value.strip().title())


def validate_imported_data(
    rows: list[dict[str, Any]],
    column_map: dict[str, int | None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate parsed rows and separate into clean and error rows.

    Parameters
    ----------
    rows : list[dict]
        Parsed rows (from ``parse_uploaded_file``).
    column_map : dict or None
        Optional pre-resolved column map. If ``None`` it is auto-detected.

    Returns
    -------
    tuple[list[dict], list[dict]]
        (clean_rows, error_rows) where each error row dict has an
        ``_errors`` key containing a list of error messages.
    """
    if not rows:
        return [], []

    # Resolve column mapping
    headers = list(rows[0].keys())
    if column_map is None:
        column_map = _resolve_column_map(headers)

    cat_col = headers[column_map["category"]]
    com_col = headers[column_map["comment"]]
    ts_col = headers[column_map["timestamp"]] if column_map.get("timestamp") is not None else None

    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows, start=2):  # +2 because 0-indexed + header
        row_errors: list[str] = []
        raw_comment = row.get(com_col, "").strip()
        raw_category = row.get(cat_col, "").strip()

        # --- Comment validation ---
        if not raw_comment:
            row_errors.append("Comment is empty or missing.")
        elif len(raw_comment) < 3:
            row_errors.append("Comment is too short (minimum 3 characters).")
        elif len(raw_comment) > 5000:
            row_errors.append("Comment exceeds the maximum length of 5000 characters.")

        # --- Category validation ---
        if not raw_category:
            row_errors.append("Category is empty or missing.")
        else:
            normalised_cat = _normalise_category(raw_category)
            if normalised_cat not in VALID_CATEGORIES and normalised_cat not in {c.value for c in EvaluationCategory}:
                row_errors.append(
                    f"Invalid category '{raw_category}'. "
                    f"Must be one of: {', '.join(c.value for c in EvaluationCategory)}"
                )

        if row_errors:
            error_entry = dict(row)  # shallow copy
            error_entry["_row"] = row_idx
            error_entry["_errors"] = row_errors
            errors.append(error_entry)
        else:
            entry = {
                "category": _normalise_category(raw_category),
                "comment": raw_comment,
            }
            if ts_col and row.get(ts_col):
                entry["timestamp"] = row[ts_col].strip()
            clean.append(entry)

    return clean, errors


# ---------------------------------------------------------------------------
# DB processing
# ---------------------------------------------------------------------------


def process_imported_evaluations(
    db: Session,
    clean_rows: list[dict[str, Any]],
    user_id: str | None = None,
    run_prediction: bool = True,
) -> ImportResult:
    """Insert validated evaluation rows into the database and optionally
    run the full sentiment prediction pipeline on each.

    Parameters
    ----------
    db : Session
        SQLAlchemy database session.
    clean_rows : list[dict]
        Validated rows (output of ``validate_imported_data``).
    user_id : str or None
        If provided, associate evaluations with this user (administrator).
    run_prediction : bool
        Whether to run the prediction pipeline on each imported evaluation.

    Returns
    -------
    ImportResult
        Summary of the import operation.
    """
    result = ImportResult()
    result.total_rows = len(clean_rows)

    for idx, row in enumerate(clean_rows):
        # Use a savepoint (nested transaction) so each row is isolated
        sp = db.begin_nested()
        try:
            evaluation = Evaluation(
                user_id=user_id,
                category=row["category"],
                comment=row["comment"],
                cleaned_comment=clean_for_classical(row["comment"]),
            )
            db.add(evaluation)
            db.flush()  # Get the evaluation ID

            if run_prediction:
                try:
                    prediction_result = run_prediction_pipeline(db, row["comment"])
                    prediction = Prediction(
                        evaluation_id=evaluation.id,
                        svm_prediction=prediction_result["svm_prediction"],
                        svm_confidence=prediction_result["svm_confidence"],
                        random_forest_prediction=prediction_result["random_forest_prediction"],
                        random_forest_confidence=prediction_result["random_forest_confidence"],
                        naive_bayes_prediction=prediction_result["naive_bayes_prediction"],
                        naive_bayes_confidence=prediction_result["naive_bayes_confidence"],
                        bert_prediction=prediction_result["bert_prediction"],
                        bert_confidence=prediction_result["bert_confidence"],
                        xgb_prediction=prediction_result["xgb_prediction"],
                        xgb_confidence=prediction_result["xgb_confidence"],
                        deberta_prediction=prediction_result["deberta_prediction"],
                        deberta_confidence=prediction_result["deberta_confidence"],
                        roberta_prediction=prediction_result["roberta_prediction"],
                        roberta_confidence=prediction_result["roberta_confidence"],
                        official_prediction=prediction_result["official_prediction"],
                        algorithm_used=prediction_result["algorithm_used"],
                        confidence_score=prediction_result["confidence_score"],
                        processing_time_ms=prediction_result["processing_time_ms"],
                    )
                    db.add(prediction)
                    # Store the official sentiment label directly on the
                    # evaluation row.
                    evaluation.sentiment = prediction_result["official_prediction"]
                except RuntimeError as exc:
                    logger.warning(
                        f"Prediction pipeline failed for imported evaluation "
                        f"({evaluation.id}): {exc}"
                    )
                    # Evaluation is still saved even if prediction fails

            sp.commit()
            result.imported += 1

        except Exception as exc:
            sp.rollback()
            logger.error(f"Failed to import row {idx + 1}: {exc}")
            result.failed += 1
            result.errors.append({
                "row": idx + 1,
                "comment": row.get("comment", "")[:100],
                "error": str(exc),
            })
            continue

    db.commit()
    logger.info(
        f"Import complete: {result.imported} imported, "
        f"{result.failed} failed out of {result.total_rows} total rows."
    )
    return result

