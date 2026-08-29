"""Admin CRUD + public read endpoint for the "Action Taken" bulletin.

Admins post aggregate updates ("Long cashier lines — second window added")
so students can see feedback leading to action without any student being
identifiable. The public endpoint projects out every internal field and
attaches only fully-aggregate per-category feedback counts.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.action_update import ActionStatus, ActionUpdate
from app.models.evaluation import Evaluation, EvaluationCategory
from app.models.prediction import Prediction, SentimentLabel
from app.models.user import User
from app.schemas.action_update import (
    ActionUpdateCreate,
    ActionUpdateOut,
    ActionUpdateUpdate,
    PublicActionUpdateOut,
    PublicBulletinResponse,
    PublicCategoryStat,
)
from app.utils.logger import logger

router = APIRouter(prefix="/action-updates", tags=["Action Updates"])


@router.get("/public", response_model=PublicBulletinResponse)
def get_public_bulletin(db: Session = Depends(get_db)):
    """Unauthenticated, read-only bulletin view.

    Returns posts (newest first) plus an aggregate feedback count for each
    category that has at least one post: how many submissions that category
    received this calendar month. Only counts, never comment text or ids.
    """
    posts = db.query(ActionUpdate).order_by(ActionUpdate.date_posted.desc()).all()

    category_stats: list[PublicCategoryStat] = []
    posted_categories = {p.category for p in posts}
    if posted_categories:
        # Aggregate counts are scoped to the current calendar month so the
        # bulletin line reads "received this month". Counts only — never
        # comment text, evaluation ids, or student ids.
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rows = (
            db.query(Evaluation.category, Prediction.official_prediction, func.count(Evaluation.id))
            .join(Prediction, Prediction.evaluation_id == Evaluation.id)
            .filter(Evaluation.created_at >= month_start)
            .group_by(Evaluation.category, Prediction.official_prediction)
            .all()
        )
        totals: dict[EvaluationCategory, int] = {}
        negatives: dict[EvaluationCategory, int] = {}
        for category, label, count in rows:
            totals[category] = totals.get(category, 0) + count
            if label == SentimentLabel.NEGATIVE:
                negatives[category] = count
        for category in EvaluationCategory:
            if category in posted_categories:
                category_stats.append(PublicCategoryStat(
                    category=category.value,
                    negative_this_month=negatives.get(category, 0),
                    total_this_month=totals.get(category, 0),
                ))

    return PublicBulletinResponse(
        posts=[PublicActionUpdateOut.model_validate(p) for p in posts],
        category_stats=category_stats,
    )


@router.get("", response_model=list[ActionUpdateOut])
def list_action_updates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return db.query(ActionUpdate).order_by(ActionUpdate.date_posted.desc()).all()


@router.post("", response_model=ActionUpdateOut, status_code=status.HTTP_201_CREATED)
def create_action_update(
    payload: ActionUpdateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    post = ActionUpdate(**payload.model_dump(), created_by=current_user.id)
    db.add(post)
    db.commit()
    db.refresh(post)
    logger.info(f"Action update created by {current_user.email}: {post.title}")
    return post


@router.patch("/{post_id}", response_model=ActionUpdateOut)
def update_action_update(
    post_id: str,
    payload: ActionUpdateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    post = db.query(ActionUpdate).filter(ActionUpdate.id == post_id).first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action update not found.")
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] == ActionStatus.RESOLVED and not (updates.get("resolution_note") or post.resolution_note):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A resolution note is required when marking a post as resolved.",
        )
    for field, value in updates.items():
        setattr(post, field, value)
    db.commit()
    db.refresh(post)
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_action_update(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    post = db.query(ActionUpdate).filter(ActionUpdate.id == post_id).first()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action update not found.")
    db.delete(post)
    db.commit()
    return None
