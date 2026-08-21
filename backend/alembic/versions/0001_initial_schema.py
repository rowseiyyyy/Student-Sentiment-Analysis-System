"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("student", "administrator", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "category",
            sa.Enum("Faculty", "Staff", "Payment", "Facilities", name="evaluationcategory"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text, nullable=False),
        sa.Column("cleaned_comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_evaluations_created_at", "evaluations", ["created_at"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "evaluation_id",
            sa.String(36),
            sa.ForeignKey("evaluations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("svm_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel"), nullable=True),
        sa.Column("svm_confidence", sa.Float, nullable=True),
        sa.Column(
            "random_forest_prediction",
            sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel"),
            nullable=True,
        ),
        sa.Column("random_forest_confidence", sa.Float, nullable=True),
        sa.Column("bert_prediction", sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel"), nullable=True),
        sa.Column("bert_confidence", sa.Float, nullable=True),
        sa.Column(
            "official_prediction",
            sa.Enum("Positive", "Neutral", "Negative", name="sentimentlabel"),
            nullable=False,
        ),
        sa.Column(
            "algorithm_used",
            sa.Enum("SVM", "Random Forest", "BERT", name="algorithmname"),
            nullable=False,
        ),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("processing_time_ms", sa.Float, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_predictions_created_at", "predictions", ["created_at"])

    op.create_table(
        "training_history",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "algorithm",
            sa.Enum("SVM", "Random Forest", "BERT", name="trainingalgorithm"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("running", "completed", "failed", name="trainingstatus"),
            nullable=False,
            server_default="running",
        ),
        sa.Column("dataset_filename", sa.String(255), nullable=True),
        sa.Column("dataset_size", sa.Integer, nullable=True),
        sa.Column("accuracy", sa.Float, nullable=True),
        sa.Column("precision", sa.Float, nullable=True),
        sa.Column("recall", sa.Float, nullable=True),
        sa.Column("f1_score", sa.Float, nullable=True),
        sa.Column("macro_f1", sa.Float, nullable=True),
        sa.Column("weighted_f1", sa.Float, nullable=True),
        sa.Column("training_time_seconds", sa.Float, nullable=True),
        sa.Column("inference_time_ms", sa.Float, nullable=True),
        sa.Column("memory_usage_mb", sa.Float, nullable=True),
        sa.Column("confusion_matrix", sa.JSON, nullable=True),
        sa.Column("classification_report", sa.JSON, nullable=True),
        sa.Column("hyperparameters", sa.JSON, nullable=True),
        sa.Column("is_production_model", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_training_history_created_at", "training_history", ["created_at"])


def downgrade() -> None:
    op.drop_table("training_history")
    op.drop_table("predictions")
    op.drop_table("evaluations")
    op.drop_table("users")

    sa.Enum(name="userrole").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="evaluationcategory").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sentimentlabel").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="algorithmname").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trainingalgorithm").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="trainingstatus").drop(op.get_bind(), checkfirst=True)
