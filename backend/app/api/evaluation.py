import secrets
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_current_user_optional, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import hash_password
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction
from app.models.user import User, UserRole
from app.schemas.evaluation import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    EvaluationCreate,
    EvaluationListResponse,
    EvaluationOut,
    StudentInfo,
)
from app.services.likert import classify_likert
from app.services.mismatch import MismatchType, detect_mismatch
from app.services.preprocessing import clean_for_classical
from app.services.prediction import run_prediction_pipeline
from app.utils.logger import logger

router = APIRouter(prefix="/evaluation", tags=["Evaluations"])

_SORTABLE_FIELDS = {
    "created_at",
    "category",
    "sentiment",
    "likert_sentiment",
    "likert_average",
    "evaluatee",
}


@router.get("/public/config")
def public_config():
    """Public config — no auth required."""
    return {}
@router.get("/config")
def get_public_config():
    """Deprecated alias for /public/config. Kept for backward compat."""
    return public_config()


def _build_text_for_sentiment(payload: EvaluationCreate) -> str | None:
    if payload.comment and payload.comment.strip():
        return payload.comment.strip()
    if payload.share_your_thoughts and payload.share_your_thoughts.strip():
        return payload.share_your_thoughts.strip()
    return None


def _attach_student_info(evaluation: Evaluation) -> StudentInfo | None:
    if evaluation.submitted_by:
        return StudentInfo(
            student_id=evaluation.submitted_by.student_id,
            course=evaluation.submitted_by.course,
            year_level=evaluation.submitted_by.year_level,
            full_name=evaluation.submitted_by.full_name,
        )
    return None


def _can_view_all_evaluations(user: User) -> bool:
    return user.role in {UserRole.ADMINISTRATOR, UserRole.FACULTY}


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def submit_evaluation(
    request: Request,
    payload: EvaluationCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    has_thoughts = bool(payload.share_your_thoughts and payload.share_your_thoughts.strip())
    has_comment = bool(payload.comment and payload.comment.strip())
    has_ratings = bool(payload.ratings)
    if not (has_thoughts or has_comment or has_ratings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide your feedback (ratings or your thoughts).",
        )

    # Server-side Likert enforcement: if ratings are submitted, they must
    # cover at least the minimum number of questions configured for the
    # form. This is a security boundary — the frontend's "answer all"
    # check is good UX but a direct API call can bypass it otherwise.
    if payload.ratings:
        required = settings.LIKERT_MIN_QUESTIONS
        provided = len(payload.ratings)
        if provided < required:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Please answer all Likert questions ({provided}/{required} provided).",
            )


    likert_label: str | None = None
    likert_average: float | None = None
    if payload.ratings:
        try:
            likert_label, likert_average = classify_likert(payload.ratings)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # User lookup/creation still needs to happen early and be flushed
    # (not committed) so we have a user_id to attach to the evaluation.
    # flush() makes the row visible within this transaction without
    # publishing it to other connections/admins the way commit() does.
    user_id = current_user.id if current_user else None
    if not current_user and payload.student_id:
        existing_user = db.query(User).filter(
            User.student_id == payload.student_id
        ).first()
        if existing_user:
            user_id = existing_user.id
            if payload.course:
                existing_user.course = payload.course
            if payload.year_level:
                existing_user.year_level = payload.year_level
        else:
            new_user = User(
                full_name=payload.student_id,
                email=f"anon-{payload.student_id}@placeholder.asiatech.local",
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                role=UserRole.STUDENT,
                student_id=payload.student_id,
                course=payload.course,
                year_level=payload.year_level,
                is_active=True,
            )
            db.add(new_user)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                existing_user = db.query(User).filter(User.student_id == payload.student_id).first()
                if existing_user is None:
                    raise
                user_id = existing_user.id
            else:
                user_id = new_user.id

    text_for_sentiment = _build_text_for_sentiment(payload)
    stored_comment = text_for_sentiment or f"{payload.category.value} evaluation (Likert only)"

    # --- Run sentiment analysis BEFORE creating/committing the Evaluation row ---
    # This is the actual fix: previously we committed the Evaluation here,
    # then ran the (slow) prediction pipeline, then committed again. That
    # left a real, fully-populated row visible to admins for however long
    # the AI models took to respond — before the student had even gotten
    # their "Submitted!" confirmation. Now nothing is written to the
    # database until we have the complete row, sentiment included.
    official_sentiment = likert_label  # default when there is no free text at all
    official_confidence: float | None = None
    prediction_result = None

    if text_for_sentiment:
        try:
            prediction_result = run_prediction_pipeline(db, text_for_sentiment)
        except RuntimeError as exc:
            # No evaluation row was ever created, so there's nothing to
            # roll back/delete here — simply surface the error.
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        official_sentiment = prediction_result["official_prediction"]
        official_confidence = prediction_result["confidence_score"]

    evaluation = Evaluation(
        user_id=user_id,
        category=payload.category,
        comment=stored_comment,
        cleaned_comment=clean_for_classical(text_for_sentiment) if text_for_sentiment else None,
        evaluatee=payload.evaluatee,
        share_your_thoughts=payload.share_your_thoughts,
        ratings=payload.ratings,
        likert_sentiment=likert_label,
        likert_average=likert_average,
        sentiment=official_sentiment,
    )

    # Mismatch is only meaningful when BOTH a Likert score and a text
    # sentiment prediction exist for this submission (see detect_mismatch
    # docstring). Ratings-only or comment-only submissions have nothing
    # to compare, so they're left as the safe defaults (False / "none").
    if likert_label is not None and text_for_sentiment and official_confidence is not None:
        mismatch = detect_mismatch(
            likert_label=likert_label,
            likert_average=likert_average,
            sentiment_label=official_sentiment,
            sentiment_confidence=official_confidence,
        )
        evaluation.is_mismatch = mismatch.is_mismatch
        evaluation.mismatch_type = mismatch.mismatch_type.value

    # --- Single commit point: the row only ever appears once, complete ---
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

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
        db.commit()

    evaluation.submitted_by = db.query(User).filter(User.id == user_id).first() if user_id else None

    return evaluation


@router.get("", response_model=EvaluationListResponse)
def list_evaluations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: EvaluationCategory | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=10000),
    search: str | None = None,
    has_submission: bool | None = Query(None, description="Filter to only entries with actual submitted content"),
    needs_review: bool | None = Query(None, description="Filter to only entries flagged as a Likert/sentiment mismatch"),
    sort_by: str | None = None,
    sort_order: str | None = "desc",
):
    query = db.query(Evaluation).options(joinedload(Evaluation.submitted_by))

    if not _can_view_all_evaluations(current_user):
        query = query.filter(Evaluation.user_id == current_user.id)

    if category is not None:
        query = query.filter(Evaluation.category == category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            Evaluation.comment.ilike(search_term)
            | Evaluation.share_your_thoughts.ilike(search_term)
            | Evaluation.evaluatee.ilike(search_term)
        )

    if has_submission:
        query = query.outerjoin(
            Prediction, Prediction.evaluation_id == Evaluation.id
        ).filter(
            (Evaluation.share_your_thoughts.isnot(None) & (Evaluation.share_your_thoughts != ""))
            | Evaluation.ratings.isnot(None)
            | Prediction.id.isnot(None)
        )

    if needs_review:
        query = query.filter(Evaluation.is_mismatch.is_(True))

    SORTABLE_FIELDS = {
        "created_at": Evaluation.created_at,
        "category": Evaluation.category,
        "sentiment": Evaluation.sentiment,
        "likert_sentiment": Evaluation.likert_sentiment,
        "likert_average": Evaluation.likert_average,
    }
    sort_column = SORTABLE_FIELDS.get(sort_by) if sort_by else None
    if sort_column is not None:
        query = query.order_by(sort_column.asc() if sort_order == "asc" else sort_column.desc())
    else:
        query = query.order_by(Evaluation.created_at.desc())

    total = query.count()
    items = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return EvaluationListResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(
    evaluation_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    evaluation = (
        db.query(Evaluation)
        .options(joinedload(Evaluation.submitted_by))
        .filter(Evaluation.id == evaluation_id)
        .first()
    )
    if not evaluation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found.")

    if not _can_view_all_evaluations(current_user) and evaluation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return evaluation


# Public configuration endpoint — no authentication required.
@router.delete("/{evaluation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_evaluation(
    evaluation_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)
):
    evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
    if not evaluation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found.")

    db.delete(evaluation)
    db.commit()
    return None


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete_evaluations(
    payload: BulkDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete multiple evaluations in one request. Accepts a list of
    evaluation ids; ids that don't exist are silently skipped and reported
    back in ``not_found`` so the admin UI can show an accurate result even
    if the table was refreshed concurrently."""

    if not payload.ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one evaluation id to delete.",
        )

    # De-dupe while preserving intent; a client could send the same id twice.
    requested_ids = list(dict.fromkeys(payload.ids))

    existing = (
        db.query(Evaluation.id)
        .filter(Evaluation.id.in_(requested_ids))
        .all()
    )
    existing_ids = {row.id for row in existing}
    not_found = [eid for eid in requested_ids if eid not in existing_ids]

    if existing_ids:
        db.query(Evaluation).filter(Evaluation.id.in_(existing_ids)).delete(
            synchronize_session=False
        )
        db.commit()

    return BulkDeleteResponse(deleted_count=len(existing_ids), not_found=list(not_found))