from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, get_current_user_optional, require_admin
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction
from app.models.user import User, UserRole
from app.schemas.evaluation import EvaluationCreate, EvaluationListResponse, EvaluationOut, StudentInfo
from app.services.likert import classify_likert
from app.services.preprocessing import clean_for_classical
from app.services.prediction import run_prediction_pipeline

router = APIRouter(prefix="/evaluation", tags=["Evaluations"])


def _build_text_for_sentiment(payload: EvaluationCreate) -> str | None:
    """Build the free-text string to run through the NLP sentiment pipeline.

    Returns ``None`` when the student provided no genuine free text (a
    Likert-only submission). Likert ratings are numeric and must never be
    paraphrased into a sentence (e.g. "Average rating: 4.5/5") and fed to
    the text sentiment models — that produces meaningless predictions on
    text the models were never trained to see. Likert scoring is handled
    separately via ``classify_likert``.
    """
    if payload.comment and payload.comment.strip():
        return payload.comment.strip()
    parts = []
    if payload.strengths and payload.strengths.strip():
        parts.append(f"Strengths: {payload.strengths.strip()}")
    if payload.areas_for_improvement and payload.areas_for_improvement.strip():
        parts.append(f"Areas for improvement: {payload.areas_for_improvement.strip()}")
    return parts[0] if parts else None


def _attach_student_info(evaluation: Evaluation) -> StudentInfo | None:
    """Attach student info from user relationship."""
    if evaluation.submitted_by:
        return StudentInfo(
            student_id=evaluation.submitted_by.student_id,
            course=evaluation.submitted_by.course,
            year_level=evaluation.submitted_by.year_level,
            full_name=evaluation.submitted_by.full_name,
        )
    return None


def _can_view_all_evaluations(user: User) -> bool:
    """Faculty and administrators can see the shared evaluation dataset for reporting."""
    return user.role in {UserRole.ADMINISTRATOR, UserRole.FACULTY}


@router.post("", response_model=EvaluationOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
def submit_evaluation(
    request: Request,
    payload: EvaluationCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Students submit Likert ratings and/or open-ended feedback. Likert
    ratings are scored with a deterministic numeric aggregation
    (``classify_likert``); free text is run through the full approved
    text-sentiment pipeline (XGBoost + DeBERTa + RoBERTa / ensembles). The
    two are independent — a submission may contain either, or both."""

    # Require at least one meaningful field: a comment, strengths /
    # areas_for_improvement, or Likert ratings. This allows imported/minimal
    # rows and Likert-only submissions to pass while still enforcing that
    # students actually submitted *something*.
    has_strengths = bool(payload.strengths and payload.strengths.strip())
    has_improvement = bool(payload.areas_for_improvement and payload.areas_for_improvement.strip())
    has_comment = bool(payload.comment and payload.comment.strip())
    has_ratings = bool(payload.ratings)
    if not (has_strengths or has_improvement or has_comment or has_ratings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide your feedback (ratings, comment, strengths, or areas for improvement).",
        )

    likert_label: str | None = None
    likert_average: float | None = None
    if payload.ratings:
        try:
            likert_label, likert_average = classify_likert(payload.ratings)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    # Handle student info for anonymous submissions (create/update user record)
    user_id = current_user.id if current_user else None
    if not current_user and payload.student_id:
        # Try to find existing user by student_id or create a new one
        existing_user = db.query(User).filter(
            User.student_id == payload.student_id
        ).first()
        if existing_user:
            user_id = existing_user.id
            # Update course/year_level if provided
            if payload.course:
                existing_user.course = payload.course
            if payload.year_level:
                existing_user.year_level = payload.year_level
        else:
            # Create a new student user
            new_user = User(
                full_name=payload.student_id,
                email=f"{payload.student_id}@asiatech.edu.ph",
                hashed_password="",  # No password for anonymous students
                role=UserRole.STUDENT,
                student_id=payload.student_id,
                course=payload.course,
                year_level=payload.year_level,
                is_active=True,
            )
            db.add(new_user)
            db.flush()
            user_id = new_user.id

    text_for_sentiment = _build_text_for_sentiment(payload)
    # `comment` is still stored for display/search even for ratings-only
    # submissions, but a placeholder is used instead of feeding a fabricated
    # sentence into the NLP pipeline (see _build_text_for_sentiment).
    stored_comment = text_for_sentiment or f"{payload.category.value} evaluation (Likert only)"

    evaluation = Evaluation(
        user_id=user_id,
        category=payload.category,
        comment=stored_comment,
        cleaned_comment=clean_for_classical(text_for_sentiment) if text_for_sentiment else None,
        evaluatee=payload.evaluatee,
        strengths=payload.strengths,
        areas_for_improvement=payload.areas_for_improvement,
        ratings=payload.ratings,
        likert_sentiment=likert_label,
        likert_average=likert_average,
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)

    official_sentiment = likert_label  # default when there is no free text at all

    if text_for_sentiment:
        try:
            result = run_prediction_pipeline(db, text_for_sentiment)
        except RuntimeError as exc:
            db.delete(evaluation)
            db.commit()
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

        prediction = Prediction(
            evaluation_id=evaluation.id,
            svm_prediction=result["svm_prediction"],
            svm_confidence=result["svm_confidence"],
            random_forest_prediction=result["random_forest_prediction"],
            random_forest_confidence=result["random_forest_confidence"],
            naive_bayes_prediction=result["naive_bayes_prediction"],
            naive_bayes_confidence=result["naive_bayes_confidence"],
            bert_prediction=result["bert_prediction"],
            bert_confidence=result["bert_confidence"],
            xgb_prediction=result["xgb_prediction"],
            xgb_confidence=result["xgb_confidence"],
            deberta_prediction=result["deberta_prediction"],
            deberta_confidence=result["deberta_confidence"],
            roberta_prediction=result["roberta_prediction"],
            roberta_confidence=result["roberta_confidence"],
            official_prediction=result["official_prediction"],
            algorithm_used=result["algorithm_used"],
            confidence_score=result["confidence_score"],
            processing_time_ms=result["processing_time_ms"],
        )
        db.add(prediction)
        db.commit()
        # The text model's official prediction takes precedence when free
        # text was actually submitted; Likert score remains stored
        # separately on the evaluation regardless (see likert_sentiment).
        official_sentiment = result["official_prediction"]

    # Store the overall sentiment label directly on the evaluation row.
    evaluation.sentiment = official_sentiment
    db.commit()
    db.refresh(evaluation)

    # Attach student info
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
    sort_by: str | None = None,
    sort_order: str | None = "desc",
):
    query = db.query(Evaluation).options(joinedload(Evaluation.submitted_by))

    # Students may only see their own submissions; faculty and administrators see all.
    if not _can_view_all_evaluations(current_user):
        query = query.filter(Evaluation.user_id == current_user.id)

    if category is not None:
        query = query.filter(Evaluation.category == category)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            Evaluation.comment.ilike(search_term)
            | Evaluation.strengths.ilike(search_term)
            | Evaluation.areas_for_improvement.ilike(search_term)
            | Evaluation.evaluatee.ilike(search_term)
        )

    # Filter to only entries that have actual submitted content (strengths or areas_for_improvement)
    if has_submission:
        query = query.filter(
            (Evaluation.strengths.isnot(None) & (Evaluation.strengths != ""))
            | (Evaluation.areas_for_improvement.isnot(None) & (Evaluation.areas_for_improvement != ""))
        )

    # Sorting
    sort_column = getattr(Evaluation, sort_by, None) if sort_by else None
    if sort_column is not None:
        order_fn = getattr(sort_column, sort_order if sort_order == "asc" else "desc", None)
        if order_fn:
            query = query.order_by(order_fn())
        else:
            query = query.order_by(Evaluation.created_at.desc())
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