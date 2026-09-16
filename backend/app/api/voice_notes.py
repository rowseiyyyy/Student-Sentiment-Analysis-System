"""Voice in a Box — anonymous open-ended feedback endpoints.

A separate feedback stream from the evaluation-form responses:

* ``POST /voice-notes`` — fully anonymous, no auth required. Runs the
  SAME live ML sentiment pipeline (Multilingual MiniLM via
  ``run_prediction_pipeline``) used for evaluation responses, so each
  entry gets a Positive/Neutral/Negative label + confidence score.
  No student identifier is accepted or stored.
* ``GET /voice-notes`` — admin/faculty read feed for the dashboard
  (sentiment filter + pagination).
* ``GET /voice-notes/stats`` — feed-local counts ONLY. Never merged
  into the evaluation analytics/KPI endpoints.
* ``DELETE /voice-notes/{id}`` — admin moderation.

These submissions must NOT affect Total Evaluations, department
breakdowns, term charts, Overview cards, or any other existing
aggregate — all of those are derived from the ``evaluations`` /
``predictions`` tables, which this module never writes to.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_admin, require_staff
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.voice_note import VoiceNote
from app.schemas.voice_note import (
    VALID_SENTIMENTS,
    VoiceNoteCreate,
    VoiceNoteListResponse,
    VoiceNoteOut,
    VoiceNoteStats,
)
from app.services.prediction import run_prediction_pipeline
from app.utils.logger import logger

router = APIRouter(prefix="/voice-notes", tags=["Voice in a Box"])


@router.post("", response_model=VoiceNoteOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def submit_voice_note(
    request: Request,
    payload: VoiceNoteCreate,
    db: Session = Depends(get_db),
):
    """Create an anonymous Voice in a Box submission.

    No authentication of any kind is required or consulted — the request
    is not tied to a user, a student ID, or a session. The message is
    scored by the same live production sentiment pipeline used for
    evaluation responses and stored with its label + confidence.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please write a message before submitting.",
        )

    try:
        result = run_prediction_pipeline(db, message)
    except RuntimeError as exc:
        logger.error(f"Voice in a Box prediction failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sentiment analysis is temporarily unavailable. Please try again shortly.",
        )

    note = VoiceNote(
        message=message,
        sentiment=result["official_prediction"],
        confidence_score=result["confidence_score"],
        algorithm_used=result["algorithm_used"],
        processing_time_ms=result["processing_time_ms"],
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("", response_model=VoiceNoteListResponse)
def list_voice_notes(
    db: Session = Depends(get_db),
    current_user: object = Depends(require_staff),
    sentiment: str | None = Query(None, description="Filter by Positive / Neutral / Negative"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """Feed of Voice in a Box submissions (admin/faculty only)."""
    query = db.query(VoiceNote)
    if sentiment:
        if sentiment not in VALID_SENTIMENTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sentiment must be one of Positive, Neutral, Negative.",
            )
        query = query.filter(VoiceNote.sentiment == sentiment)

    total = query.count()
    items = (
        query.order_by(VoiceNote.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return VoiceNoteListResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/stats", response_model=VoiceNoteStats)
def voice_note_stats(
    db: Session = Depends(get_db),
    current_user: object = Depends(require_staff),
):
    """Feed-local counts for the Voice in a Box stream.

    Deliberately separate from /analytics — these numbers never feed the
    Total Evaluations KPI, department breakdowns, or term charts.
    """
    total = db.query(func.count(VoiceNote.id)).scalar() or 0
    positive = (
        db.query(func.count(VoiceNote.id)).filter(VoiceNote.sentiment == "Positive").scalar() or 0
    )
    neutral = (
        db.query(func.count(VoiceNote.id)).filter(VoiceNote.sentiment == "Neutral").scalar() or 0
    )
    negative = (
        db.query(func.count(VoiceNote.id)).filter(VoiceNote.sentiment == "Negative").scalar() or 0
    )
    return VoiceNoteStats(total=total, positive=positive, neutral=neutral, negative=negative)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice_note(
    note_id: str,
    db: Session = Depends(get_db),
    current_user: object = Depends(require_admin),
):
    note = db.query(VoiceNote).filter(VoiceNote.id == note_id).first()
    if not note:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice note not found.")
    db.delete(note)
    db.commit()
    return None
