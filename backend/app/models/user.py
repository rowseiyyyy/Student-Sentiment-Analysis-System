import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(str, enum.Enum):
    STUDENT = "student"
    ADMINISTRATOR = "administrator"
    FACULTY = "faculty"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.STUDENT, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # New fields for student info
    student_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    course: Mapped[str | None] = mapped_column(String(150), nullable=True)
    year_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # NOTE: cascade intentionally excludes "delete"/"delete-orphan". The
    # Evaluation.user_id FK is ondelete="SET NULL" -- evaluation/prediction
    # history must survive a user record being deleted (research data must
    # be preserved). "all, delete-orphan" would instead have SQLAlchemy
    # actively delete every Evaluation belonging to a deleted User.
    evaluations = relationship("Evaluation", back_populates="submitted_by", cascade="save-update, merge")