"""
File import service for bulk-uploading compiled student evaluation data
from Excel (.xlsx, .xls) and CSV (.csv) files exported from Google Forms.

Rewritten to import FULL evaluation-form-equivalent data (not just a
bare comment + category), so imported rows behave identically to a
normal student submission through the live form:

  - Student ID / Course / Year Level  -> looked up or created as a User,
    exactly like app.api.evaluation.submit_evaluation does. Rows with no
    Student ID are imported anonymously (user_id = None), same as the
    live anonymous flow.
  - Evaluatee (professor name)         -> Evaluation.evaluatee
  - Open-ended comment                 -> Evaluation.share_your_thoughts
    (NOT Evaluation.comment — that field is reserved for the
    Likert-only fallback text, matching submit_evaluation's behavior).
  - Likert ratings (1-5 per aspect)    -> Evaluation.ratings (JSON),
    using the SAME aspect keys as the live forms in student.js, scoped
    per category (Faculty/Staff/Facilities/Payment each have a
    different question set).
  - Sentiment is ALWAYS computed here via run_prediction_pipeline
    (XGBoost + DeBERTa + RoBERTa ensemble) — a Sentiment column in the
    uploaded file, if present, is intentionally ignored.

One file = one category. The admin selects the category (Faculty /
Staff / Facilities / Payment) in the UI before uploading, because each
category's Google Form has a different rating-question layout and
mixing them in one auto-detected pass is unreliable. A Category column
in the file, if present, is only cross-checked against the selection
and never trusted on its own.

Workflow
--------
1. parse_uploaded_file      — reads the raw file into a list of dicts.
2. validate_imported_data   — resolves columns, validates each row,
                               returns (clean_rows, error_rows).
3. process_imported_evaluations — creates/looks-up Users, runs the
                               live prediction pipeline, and inserts
                               full Evaluation + Prediction records.
"""
from __future__ import annotations

import csv
import re
import secrets
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction
from app.models.user import User, UserRole
from app.services.likert import classify_likert
from app.services.mismatch import detect_mismatch
from app.services.prediction import run_prediction_pipeline
from app.services.preprocessing import clean_for_classical
from app.utils.logger import logger

# ---------------------------------------------------------------------------
# Column detection keywords
# ---------------------------------------------------------------------------

CATEGORY_COL_KEYWORDS = [
    "category", "categories", "aspect", "area", "type",
    "evaluation category", "evaluation aspect",
]

COMMENT_COL_KEYWORDS = [
    "share your thoughts", "your thoughts", "comment", "comments",
    "feedback", "suggestion", "suggestions", "remarks", "review",
    "message", "text", "response", "your feedback", "your comments",
    "your suggestions", "open-ended feedback", "student feedback",
]

EVALUATEE_COL_KEYWORDS = [
    "evaluatee", "professor", "professor name", "instructor",
    "instructor name", "select the professor", "name of professor",
    "staff name", "subject/course handled",
]

STUDENT_ID_COL_KEYWORDS = [
    "student id", "student number", "student no", "id number", "id no",
]

COURSE_COL_KEYWORDS = ["course", "program", "course/program"]

YEAR_LEVEL_COL_KEYWORDS = ["year level", "year"]

TIMESTAMP_COL_KEYWORDS = [
    "timestamp", "date", "time", "submitted", "submission date",
    "submission time", "datetime", "date submitted",
]

# Per-category Likert aspect keys, mapped to the keyword(s) most likely
# to appear in a Google Form export header for that question. These
# mirror the exact question text used in js/student.js so headers that
# are the full question (Google Forms' default export behavior) still
# match via substring search.
RATING_KEYWORDS_BY_CATEGORY: dict[str, dict[str, list[str]]] = {
    "Faculty": {
        "mastery": ["mastery of the subject", "mastery"],
        "teaching_quality": ["teaching quality", "good teaching"],
        "clarity": ["communicates and explains", "clarity"],
        "fairness": ["grades and evaluates", "fairness", "fairly"],
        "punctuality": ["punctuality and attendance", "punctuality"],
        "approachability": ["approachability"],
        "classroom_mgmt": ["classroom management"],
    },
    "Staff": {
        "safety": ["guards make me feel safe", "safety"],
        "registrar": ["registrar"],
        "cashier": ["cashier"],
        "canteen": ["canteen"],
        "substitute": ["substitutes and temporary staff", "substitute"],
        "office_staff": ["office staff"],
        "admin_comm": ["administration keeps students", "admin_comm", "well-informed"],
        "maintenance": ["maintenance staff", "maintenance"],
    },
    "Facilities": {
        "spaces": ["great spaces", "benches, study areas", "spaces"],
        "furniture": ["tables and chairs", "furniture"],
        "cleanliness": ["general cleanliness", "cleanliness"],
        "bathrooms": ["bathrooms"],
        "cafeteria": ["cafeteria"],
        "monitors": ["classroom monitor", "monitors"],
        "computers": ["laboratory computers", "computers"],
        "classrooms": ["classrooms are bright", "classrooms"],
    },
    "Payment": {
        "accessibility": ["payment portal", "accessib"],
        "processing": ["processed promptly", "processing"],
        "queues": ["payment queues", "queues"],
        "online": ["online payment", "online"],
        "courteous": ["payment personnel are courteous", "courteous"],
        "accounting": ["accounting and registrar personnel", "accounting"],
        "security": ["personal and financial information is secure", "security"],
    },
}

VALID_CATEGORIES = {c.value for c in EvaluationCategory}

# ---------------------------------------------------------------------------
# Combined multi-category import support (auto-detected)
# ---------------------------------------------------------------------------
# A "combined" dataset holds, in one row per respondent, rating + comment
# columns for ALL four categories, each prefixed by its category:
#   Respondent_ID, Course, [Year Level],
#   Staff_Safety, Staff_Registrar, ..., Staff_Comments,
#   Professor_TeachingQuality, ..., Professor_Comments,
#   Facilities_Spaces, ..., Facilities_Comments,
#   Payments_Accessibility, ..., Payments_Comments
# detect_import_mode() spots this format (>= 2 category prefixes in the
# header); _validate_combined() then splits each row into up to four
# Evaluation records so the rest of the pipeline (prediction, mismatch
# detection, DB insert) is identical to a normal per-category submission.
COMBINED_CATEGORY_PREFIXES = {
    "staff_": "Staff",
    "professor_": "Faculty",      # "Professor_" prefix maps to the Faculty category
    "facilities_": "Facilities",
    "payments_": "Payment",       # "Payments_" prefix maps to the Payment category
}

# Canonical Likert aspect keys per category, taken verbatim from the live
# student forms in js/student.js. A combined rating column is only kept if
# its derived aspect key is in this set (else it's treated as a stray column).
ASPECT_KEYS_BY_CATEGORY = {
    "Faculty": [
        "teaching_quality", "mastery", "clarity", "fairness",
        "punctuality", "approachability", "feedback",
        "classroom_mgmt", "teaching_style",
    ],
    "Staff": [
        "safety", "registrar", "cashier", "canteen", "substitute",
        "office_staff", "admin_comm", "maintenance",
    ],
    "Facilities": [
        "spaces", "furniture", "cleanliness", "bathrooms", "cafeteria",
        "monitors", "computers", "classrooms",
    ],
    "Payment": [
        "accessibility", "processing", "queues", "courteous",
        "accounting", "security", "info_clarity", "digital_trust",
    ],
}

# Pre-computed lowercased / de-punctuated lookup so column headers match
# the aspect keys regardless of case or CamelCase vs snake_case styling:
#   'TeachingQuality' -> 'teachingquality' -> 'teaching_quality'
#   'InfoClarity'    -> 'infoclarity'      -> 'info_clarity'
_ASPECT_LOOKUP_BY_CATEGORY = {
    category: {re.sub(r"[^a-z0-9]", "", k): k for k in keys}
    for category, keys in ASPECT_KEYS_BY_CATEGORY.items()
}


def _compact(value: str) -> str:
    """Lowercase and strip all non-alphanumeric chars for tolerant matching."""
    return re.sub(r"[^a-z0-9]", "", _normalise_header(value))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ImportValidationError(Exception):
    """Raised when the uploaded file fails structural validation."""


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


class ImportResult:
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
    return " ".join(str(name).strip().lower().split())


def _find_column(headers: list[str], keywords: list[str]) -> str | None:
    """Return the original header text of the first column whose
    normalised text contains (or is contained in) any keyword."""
    normalised = {h: _normalise_header(h) for h in headers}
    for kw in keywords:
        kw_norm = _normalise_header(kw)
        for original, norm in normalised.items():
            if kw_norm in norm or norm in kw_norm:
                return original
    return None


def _find_rating_columns(headers: list[str], category: str) -> dict[str, str]:
    """Return {aspect_key: header_text} for every Likert aspect column
    detected for the given category."""
    keyword_map = RATING_KEYWORDS_BY_CATEGORY.get(category, {})
    found: dict[str, str] = {}
    normalised = {h: _normalise_header(h) for h in headers}
    for aspect_key, keywords in keyword_map.items():
        for kw in keywords:
            kw_norm = _normalise_header(kw)
            match = next((orig for orig, norm in normalised.items() if kw_norm in norm), None)
            if match:
                found[aspect_key] = match
                break
    return found


def resolve_column_map(headers: list[str], category: str) -> dict[str, Any]:
    """Resolve all relevant columns for the given category.

    Raises ImportValidationError if a Comment-equivalent column can't
    be found — that's the one column every row must have.
    """
    comment_col = _find_column(headers, COMMENT_COL_KEYWORDS)
    if comment_col is None:
        raise ImportValidationError(
            "Could not find a 'Share your thoughts' / comment column. "
            "Expected a header containing one of: "
            f"{COMMENT_COL_KEYWORDS[:5]}..."
        )

    return {
        "category": _find_column(headers, CATEGORY_COL_KEYWORDS),
        "comment": comment_col,
        "evaluatee": _find_column(headers, EVALUATEE_COL_KEYWORDS),
        "student_id": _find_column(headers, STUDENT_ID_COL_KEYWORDS),
        "course": _find_column(headers, COURSE_COL_KEYWORDS),
        "year_level": _find_column(headers, YEAR_LEVEL_COL_KEYWORDS),
        "timestamp": _find_column(headers, TIMESTAMP_COL_KEYWORDS),
                "ratings": _find_rating_columns(headers, category),
    }


# ---------------------------------------------------------------------------
# Combined multi-category resolution helpers
# ---------------------------------------------------------------------------


def _detect_category_prefix(header: str) -> str | None:
    """If *header* is a combined-format column (Staff_* / Professor_* /
    Facilities_* / Payments_*), return the lowercase prefix, else None."""
    norm = _normalise_header(header)
    for prefix in COMBINED_CATEGORY_PREFIXES:
        if norm.startswith(prefix):
            return prefix
    return None


def detect_import_mode(headers: list[str]) -> str:
    """Return 'combined' when the header row spans two or more category
    prefixes (a multi-category dataset), otherwise 'single'."""
    prefixes_found = {_detect_category_prefix(h) for h in headers}
    prefixes_found.discard(None)
    return "combined" if len(prefixes_found) >= 2 else "single"


def _resolve_combined_columns(headers: list[str]) -> dict[str, Any]:
    """Map a combined file's columns into a structured description.

    Returns a dict with top-level identity columns (respondent_id, course,
    year_level, timestamp) and a per-category breakdown of rating headers,
    comment header, and (for Faculty) an optional evaluatee header.
    """
    col_map: dict[str, Any] = {
        "respondent_id": None,
        "course": None,
        "year_level": None,
        "timestamp": None,
        "categories": {},
    }
    for h in headers:
        prefix = _detect_category_prefix(h)
        if prefix:
            category = COMBINED_CATEGORY_PREFIXES[prefix]
            # Preserve the original header's case for word-boundary recovery;
            # derive the aspect key from the portion after the prefix.
            remainder = h[len(prefix):]
            compact_remainder = _compact(remainder)
            cat_cols = col_map["categories"].setdefault(
                category, {"ratings": {}, "comment": None, "evaluatee": None}
            )
            lookup = _ASPECT_LOOKUP_BY_CATEGORY.get(category, {})
            if compact_remainder in ("comment", "comments"):
                cat_cols["comment"] = h
            elif compact_remainder in lookup:
                cat_cols["ratings"][lookup[compact_remainder]] = h
            elif category == "Faculty" and compact_remainder in (
                "professor", "professorname", "name"
            ):
                cat_cols["evaluatee"] = h
            # any other remainder is a stray/unknown column and is ignored
        else:
            # top-level identity columns (not prefixed by a category)
            if _normalise_header(h) == "respondent_id":
                col_map["respondent_id"] = h
            elif _find_column([h], COURSE_COL_KEYWORDS) == h:
                col_map["course"] = h
            elif _find_column([h], STUDENT_ID_COL_KEYWORDS) == h:
                col_map["respondent_id"] = h
            elif _find_column([h], YEAR_LEVEL_COL_KEYWORDS) == h:
                col_map["year_level"] = h
            elif _find_column([h], TIMESTAMP_COL_KEYWORDS) == h:
                col_map["timestamp"] = h
    return col_map


def _parse_combined_row(
    row: dict[str, Any], col_map: dict[str, Any], row_idx: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Expand one combined spreadsheet row into per-category clean rows.

    Each returned clean row has the same shape validate_imported_data
    produces for single-category files, so process_imported_evaluations
    can treat them identically. A category with neither ratings nor a
    comment is skipped silently; a row that is empty across *every*
    category is reported as an error.
    """
    clean_rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def _cell(col_key: str) -> str:
        header = col_map[col_key]
        return (row.get(header) or "") if header else ""

    student_id = _cell("respondent_id").strip() or None
    course = _cell("course").strip() or None
    year_level = _cell("year_level").strip() or None
    timestamp = _cell("timestamp").strip() or None

    any_category_data = False
    for category in ("Faculty", "Staff", "Facilities", "Payment"):
        cat_cols = col_map["categories"].get(category)
        if not cat_cols:
            continue

        ratings: dict[str, int] = {}
        for aspect, header in (cat_cols.get("ratings") or {}).items():
            parsed = _parse_rating_value(row.get(header, ""))
            if parsed is not None:
                ratings[aspect] = parsed

        raw_comment = ""
        if cat_cols.get("comment"):
            raw_comment = (row.get(cat_cols["comment"]) or "").strip()

        evaluatee = None
        if cat_cols.get("evaluatee"):
            evaluatee = (row.get(cat_cols["evaluatee"]) or "").strip() or None

        if not raw_comment and not ratings:
            continue  # no data for this category -> skip silently
        any_category_data = True

        if raw_comment and len(raw_comment) < 3:
            errors.append({
                "_row": row_idx,
                "_errors": [f"{category} comment is too short (minimum 3 characters)."],
                "_preview": raw_comment[:100],
            })
            continue
        if len(raw_comment) > 5000:
            errors.append({
                "_row": row_idx,
                "_errors": [
                    f"{category} comment exceeds the maximum length of 5000 characters."
                ],
                "_preview": raw_comment[:100],
            })
            continue

        clean_rows.append({
            "category": category,
            "share_your_thoughts": raw_comment or None,
            "evaluatee": evaluatee if category == "Faculty" else None,
            "ratings": ratings or None,
            "student_id": student_id,
            "course": course,
            "year_level": year_level,
            "timestamp": timestamp,
        })

    if not any_category_data:
        errors.append({
            "_row": row_idx,
            "_errors": [
                "Row has no feedback in any category "
                "(Staff, Professor, Facilities, Payments)."
            ],
            "_preview": "",
        })

    return clean_rows, errors


def _validate_combined(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a combined multi-category dataset.

    Returns (clean_rows, error_rows). Each spreadsheet row expands into
    up to four clean rows (one per non-empty category), each shaped for
    process_imported_evaluations.
    """
    headers = list(rows[0].keys())
    col_map = _resolve_combined_columns(headers)

    if not col_map["categories"]:
        raise ImportValidationError(
            "A combined file was detected (multiple category prefixes in the "
            "header) but no Staff_/Professor_/Facilities_/Payments_ rating or "
            "comment columns were resolved."
        )

    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows, start=2):  # +2: header row + 0-index
        row_clean, row_errors = _parse_combined_row(row, col_map, row_idx)
        clean.extend(row_clean)
        errors.extend(row_errors)

    return clean, errors


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
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        return [[cell.strip() for cell in row] for row in reader]


def _read_excel_rows(file_path: Path) -> list[list[str]]:
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active
    rows: list[list[str]] = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(cell).strip() if cell is not None else "" for cell in row])
    wb.close()
    return rows


def parse_uploaded_file(file_path: Path) -> list[dict[str, Any]]:
    ext = file_path.suffix.lower()
    logger.info(f"Parsing uploaded file: {file_path.name} (format: {ext})")

    raw_rows = _read_csv_rows(file_path) if ext == ".csv" else _read_excel_rows(file_path)

    if not raw_rows:
        raise ImportValidationError("The uploaded file appears to be empty.")

    headers = raw_rows[0]
    data_rows = raw_rows[1:]

    if not data_rows:
        raise ImportValidationError("The uploaded file contains a header row but no data rows.")

    result = []
    for row in data_rows:
        while len(row) < len(headers):
            row.append("")
        # Skip fully blank rows (common trailing rows in Excel exports)
        if not any(cell.strip() for cell in row):
            continue
        result.append(dict(zip(headers, row)))

    logger.info(f"Parsed {len(result)} data rows from {file_path.name}")
    return result


# ---------------------------------------------------------------------------
# Value parsing helpers
# ---------------------------------------------------------------------------


def _parse_rating_value(raw: str) -> int | None:
    """Parse a Likert cell into an int 1-5. Handles plain numbers as
    well as Google Forms' common 'X - Label' export format."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        val = int(float(raw))
        if 1 <= val <= 5:
            return val
    except ValueError:
        pass
    match = re.search(r"[1-5]", raw)
    if match:
        return int(match.group())
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_imported_data(
    rows: list[dict[str, Any]],
    category: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate parsed rows and return (clean_rows, error_rows).

    Auto-detects the import mode from the header row:

      * 'combined' — a single file carrying all four categories per row
        (columns prefixed Staff_ / Professor_ / Facilities_ / Payments_*).
        The ``category`` argument is ignored; each row expands to up to
        four Evaluation records (one per category that has data).
      * 'single'   — one category per file (e.g. a Google Form export).
        The admin-selected ``category`` is required and used to resolve
        the rating-question columns.

    Each clean row is a dict ready for process_imported_evaluations:
    category, share_your_thoughts, evaluatee, ratings, student_id,
    course, year_level, timestamp.
    """
    if not rows:
        return [], []

    headers = list(rows[0].keys())
    if detect_import_mode(headers) == "combined":
        logger.info("Auto-detected combined multi-category import file.")
        return _validate_combined(rows)

    # --- single-category mode (one category per file) ---
    if category is None:
        raise ImportValidationError(
            "Could not detect a combined multi-category file and no category "
            "was supplied. Resubmit with a category selected, or include "
            "columns from at least two of Staff_/Professor_/Facilities_/Payments_."
        )
    if category not in VALID_CATEGORIES:
        raise ImportValidationError(
            f"'{category}' is not a valid category. Must be one of: {sorted(VALID_CATEGORIES)}"
        )

    col_map = resolve_column_map(headers, category)

    clean: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for row_idx, row in enumerate(rows, start=2):  # +2: header row + 0-index
        row_errors: list[str] = []

        raw_comment = (row.get(col_map["comment"]) or "").strip()

        ratings: dict[str, int] = {}
        for aspect_key, header in col_map["ratings"].items():
            parsed = _parse_rating_value(row.get(header, ""))
            if parsed is not None:
                ratings[aspect_key] = parsed

        # A row needs at least a comment OR at least one rating —
        # mirrors the live submit_evaluation requirement.
        if not raw_comment and not ratings:
            row_errors.append("Row has neither a comment nor any ratings filled in.")
        elif raw_comment and len(raw_comment) < 3:
            row_errors.append("Comment is too short (minimum 3 characters).")
        elif len(raw_comment) > 5000:
            row_errors.append("Comment exceeds the maximum length of 5000 characters.")

        # Cross-check an in-file category column, if present, against
        # the admin's selection — mismatch is a warning-level error so
        # a student who submitted the wrong form doesn't get silently
        # miscategorized.
        if col_map["category"]:
            file_cat = (row.get(col_map["category"]) or "").strip()
            if file_cat and file_cat.lower() != category.lower():
                row_errors.append(
                    f"Row's Category column says '{file_cat}' but you selected "
                    f"'{category}' for this import — skipped to avoid miscategorizing it."
                )

        evaluatee = None
        if col_map["evaluatee"]:
            evaluatee = (row.get(col_map["evaluatee"]) or "").strip() or None
            if category != "Faculty":
                evaluatee = None  # evaluatee is only meaningful for Faculty

        student_id = (row.get(col_map["student_id"]) or "").strip() if col_map["student_id"] else ""
        course = (row.get(col_map["course"]) or "").strip() if col_map["course"] else ""
        year_level = (row.get(col_map["year_level"]) or "").strip() if col_map["year_level"] else ""
        timestamp = (row.get(col_map["timestamp"]) or "").strip() if col_map["timestamp"] else ""

        if row_errors:
            error_entry = {
                "_row": row_idx,
                "_errors": row_errors,
                "_preview": raw_comment[:100] or f"({category} — ratings only)",
            }
            errors.append(error_entry)
        else:
            clean.append({
                "category": category,
                "share_your_thoughts": raw_comment or None,
                "evaluatee": evaluatee,
                "ratings": ratings or None,
                "student_id": student_id or None,
                "course": course or None,
                "year_level": year_level or None,
                "timestamp": timestamp or None,
            })

    return clean, errors


# ---------------------------------------------------------------------------
# DB processing — mirrors app.api.evaluation.submit_evaluation
# ---------------------------------------------------------------------------


def _get_or_create_student_user(db: Session, student_id: str, course: str | None, year_level: str | None) -> str | None:
    """Look up or create a User for this student_id, same pattern as
    submit_evaluation. Returns the user_id, or None on failure."""
    existing_user = db.query(User).filter(User.student_id == student_id).first()
    if existing_user:
        if course:
            existing_user.course = course
        if year_level:
            existing_user.year_level = year_level
        return existing_user.id

    new_user = User(
        full_name=student_id,
        email=f"anon-{student_id}@placeholder.asiatech.local",
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.STUDENT,
        student_id=student_id,
        course=course,
        year_level=year_level,
        is_active=True,
    )
    db.add(new_user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing_user = db.query(User).filter(User.student_id == student_id).first()
        return existing_user.id if existing_user else None
    return new_user.id


def process_imported_evaluations(
    db: Session,
    clean_rows: list[dict[str, Any]],
    run_prediction: bool = True,
) -> ImportResult:
    """Insert validated rows as full Evaluation records — same shape,
    same prediction pipeline, same mismatch detection as a live
    student submission via POST /evaluation. NOTE: unlike the previous
    version of this function, this does NOT attribute rows to the
    importing admin. Each row is attributed to its own student_id (if
    given) or left anonymous (user_id = None), matching the live flow."""
    result = ImportResult()
    result.total_rows = len(clean_rows)

    for idx, row in enumerate(clean_rows):
        sp = db.begin_nested()
        try:
            user_id = None
            if row.get("student_id"):
                user_id = _get_or_create_student_user(
                    db, row["student_id"], row.get("course"), row.get("year_level")
                )

            likert_label = None
            likert_average = None
            if row.get("ratings"):
                likert_label, likert_average = classify_likert(row["ratings"])

            text_for_sentiment = row.get("share_your_thoughts")
            stored_comment = text_for_sentiment or f"{row['category']} evaluation (Likert only)"

            official_sentiment = likert_label
            official_confidence = None
            prediction_result = None

            if run_prediction and text_for_sentiment:
                prediction_result = run_prediction_pipeline(db, text_for_sentiment)
                official_sentiment = prediction_result["official_prediction"]
                official_confidence = prediction_result["confidence_score"]

            evaluation = Evaluation(
                user_id=user_id,
                category=EvaluationCategory(row["category"]),
                comment=stored_comment,
                cleaned_comment=clean_for_classical(text_for_sentiment) if text_for_sentiment else None,
                evaluatee=row.get("evaluatee"),
                share_your_thoughts=text_for_sentiment,
                ratings=row.get("ratings"),
                likert_sentiment=likert_label,
                likert_average=likert_average,
                sentiment=official_sentiment,
            )

            if likert_label is not None and text_for_sentiment and official_confidence is not None:
                mismatch = detect_mismatch(
                    likert_label=likert_label,
                    likert_average=likert_average,
                    sentiment_label=official_sentiment,
                    sentiment_confidence=official_confidence,
                )
                evaluation.is_mismatch = mismatch.is_mismatch
                evaluation.mismatch_type = mismatch.mismatch_type.value

            db.add(evaluation)
            db.flush()

            if prediction_result is not None:
                prediction = Prediction(
                    evaluation_id=evaluation.id,
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

            sp.commit()
            result.imported += 1

        except Exception as exc:
            sp.rollback()
            logger.error(f"Failed to import row {idx + 1}: {exc}")
            result.failed += 1
            result.errors.append({
                "row": idx + 1,
                "comment": (row.get("share_your_thoughts") or "")[:100],
                "error": str(exc),
            })
            continue

    db.commit()
    logger.info(
        f"Import complete: {result.imported} imported, "
        f"{result.failed} failed out of {result.total_rows} total rows."
    )
    return result