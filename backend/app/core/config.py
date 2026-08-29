"""
Application configuration.

All values are loaded from environment variables (or a .env file in the
backend/ root). Sensible development defaults are provided so the project
runs out of the box, but every value should be overridden in production.
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


def _resolve_config_path(value: str | Path | None, base_dir: Path = BASE_DIR) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    PROJECT_NAME: str = "Asiatech Sentiment Analysis API"
    PROJECT_DESCRIPTION: str = (
        "Sentiment Analysis of Student Feedback from Asiatech College of "
        "Sta. Rosa, Laguna using XGBoost, DeBERTa and RoBERTa."
    )
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development")  # development | production
    DEBUG: bool = True

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug_value(cls, value: object) -> object:
        """Accept common environment labels in addition to boolean values.

        Some Windows environments set ``DEBUG=release``.  Pydantic only
        accepts boolean strings by default, which prevented the application
        (and its test suite) from starting.  Treat release/production as
        disabled debugging and development/debug as enabled debugging.
        """
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "production"}:
                return False
            if normalized in {"debug", "development"}:
                return True
        return value

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    # IMPORTANT: every value below MUST be overridden in production via
    # environment variables. A startup guard further down refuses to boot
    # in production with the default SECRET_KEY.
    SECRET_KEY: str = Field(default="change-me-in-production-please-use-a-long-random-string")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    # Default is wide-open for local development. In production, set
    # CORS_ORIGINS to your frontend origin(s) only, e.g.
    #   CORS_ORIGINS=["https://feedback.asiatech.edu.ph"]
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "https://student-sentiment-snalysis-system.vercel.app",
    ]

    # Minimum number of Likert questions that must be answered when a
    # submission includes ratings. Prevents API-level abuse where a
    # partial/empty ratings payload bypasses the frontend's "answer all"
    # enforcement. Should match (or exceed) the number of questions in
    # the evaluation form.
    LIKERT_MIN_QUESTIONS: int = 5
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "asiatech_sentiment_db"
    DB_DRIVER: str = Field(default="mysql+pymysql")  # "mysql+pymysql" | "sqlite"

    # Temporary validation-only override: when set, all ML artifacts and the
    # validation database are redirected below this root without modifying the
    # default production paths.
    TEMP_VALIDATION_ROOT: Path | None = None
    VALIDATION_DB_NAME: str | None = None
    VALIDATION_SQLITE_PATH: Path | None = None

    @property
    def DATABASE_URL(self) -> str:
        if self.DB_DRIVER == "sqlite":
            sqlite_path = self.VALIDATION_SQLITE_PATH
            if sqlite_path is None and self.TEMP_VALIDATION_ROOT is not None:
                sqlite_path = self.TEMP_VALIDATION_ROOT / "validation.db"
            if sqlite_path is None:
                return f"sqlite:///{BASE_DIR / 'asiatech_sentiment.db'}"
            sqlite_target = _resolve_config_path(sqlite_path)
            return f"sqlite:///{sqlite_target}"
        if self.VALIDATION_DB_NAME:
            db_name = self.VALIDATION_DB_NAME
        else:
            db_name = self.DB_NAME
        return (
            f"{self.DB_DRIVER}://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{db_name}"
        )

    # ------------------------------------------------------------------
    # Security / JWT
    # ------------------------------------------------------------------
    SECRET_KEY: str = "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_1234567890"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days


    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_PREDICT: str = "20/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    # ------------------------------------------------------------------
    # ML / Model paths
    # ------------------------------------------------------------------
    ML_DIR: Path = BASE_DIR / "app" / "ml"
    DATASETS_DIR: Path = BASE_DIR / "app" / "datasets"

    # Active paths.
    XGB_MODEL_PATH: Path = ML_DIR / "xgb_model.pkl"
    XGB_TFIDF_VECTORIZER_PATH: Path = ML_DIR / "tfidf_vectorizer_xgb.pkl"
    XGB_LABEL_ENCODER_PATH: Path = ML_DIR / "label_encoder_xgb.pkl"
    DEBERTA_MODEL_PATH: Path = ML_DIR / "deberta_v3"
    ROBERTA_MODEL_PATH: Path = ML_DIR / "roberta_sentiment"

    MODEL_METADATA_PATH: Path = ML_DIR / "model_metadata.json"
    COMPARISON_RESULTS_PATH: Path = ML_DIR / "comparison_results.json"

    # General RoBERTa is fine-tuned on the actual student-feedback labels;
    # avoid treating a Twitter-domain sentiment checkpoint as a final model.
    ROBERTA_MODEL_NAME: str = "roberta-base"
    DEBERTA_MODEL_NAME: str = "microsoft/deberta-v3-base"

    TRANSFORMER_DEVICE: str = "cpu"

    RANDOM_STATE: int = 42
    TEST_SIZE: float = 0.2

    # ------------------------------------------------------------------
    # Ensemble / evaluation
    # ------------------------------------------------------------------
    # Initial weights for the soft-vote ensemble. These are NOT claimed
    # to be optimal; they are starting values for the ensemble.
    ENSEMBLE_WEIGHTS: dict[str, float] = {
        "DeBERTa": 0.4,
        "RoBERTa": 0.4,
        "XGBoost": 0.2,
    }
    BOOTSTRAP_N_ITER: int = 1000
    BOOTSTRAP_ALPHA: float = 0.05
    BOOTSTRAP_SEED: int = 42

    # DeBERTa fine-tune defaults (initial configuration; not validated
    # as optimal until a real labelled training/evaluation run).
    DEBERTA_EPOCHS: int = 3
    DEBERTA_BATCH_SIZE: int = 8
    DEBERTA_LEARNING_RATE: float = 2e-5
    DEBERTA_WEIGHT_DECAY: float = 0.01
    DEBERTA_WARMUP_RATIO: float = 0.1
    DEBERTA_MAX_SEQ_LENGTH: int = 256


    # XGBoost defaults.
    XGB_N_ESTIMATORS: int = 300
    XGB_MAX_DEPTH: int = 6
    XGB_LEARNING_RATE: float = 0.1

    # Stopword removal is OFF by default. Set
    # `PREPROCESSING_REMOVE_STOPWORDS=true` in `.env` to enable.
    PREPROCESSING_REMOVE_STOPWORDS: bool = False

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_DIR: Path = BASE_DIR / "logs"
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    settings = Settings()

    validation_root = _resolve_config_path(os.getenv("TEMP_VALIDATION_ROOT"))
    if validation_root is None:
        validation_root = settings.TEMP_VALIDATION_ROOT
    if validation_root is not None:
        settings.TEMP_VALIDATION_ROOT = validation_root
        settings.ML_DIR = validation_root / "ml"
        settings.DATASETS_DIR = validation_root / "datasets"
        settings.XGB_MODEL_PATH = settings.ML_DIR / "xgb_model.pkl"
        settings.XGB_TFIDF_VECTORIZER_PATH = settings.ML_DIR / "tfidf_vectorizer_xgb.pkl"
        settings.XGB_LABEL_ENCODER_PATH = settings.ML_DIR / "label_encoder_xgb.pkl"
        settings.DEBERTA_MODEL_PATH = settings.ML_DIR / "deberta_v3"
        settings.ROBERTA_MODEL_PATH = settings.ML_DIR / "roberta_sentiment"
        settings.MODEL_METADATA_PATH = settings.ML_DIR / "model_metadata.json"
        settings.COMPARISON_RESULTS_PATH = settings.ML_DIR / "comparison_results.json"

        validation_db_name = os.getenv("VALIDATION_DB_NAME")
        if validation_db_name:
            settings.VALIDATION_DB_NAME = validation_db_name
        if settings.DB_DRIVER == "sqlite":
            validation_sqlite = _resolve_config_path(os.getenv("VALIDATION_SQLITE_PATH"))
            if validation_sqlite is None:
                validation_sqlite = validation_root / "validation.db"
            settings.VALIDATION_SQLITE_PATH = validation_sqlite

    settings.ML_DIR.mkdir(parents=True, exist_ok=True)
    settings.DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()


def assert_production_readiness() -> None:
    """Refuse to boot in production with unsafe defaults.

    Called once at startup from main.py. Checks that DEBUG is off,
    SECRET_KEY has been changed from the default, and CORS is not
    wide-open. Any failure logs the specific issue and raises
    RuntimeError so the process exits before serving traffic.
    """
    # Local import avoids a circular import at module load time
    # (config ← logger ← config). By the time this runs at startup,
    # both modules are fully initialized.
    from app.utils.logger import logger

    if settings.ENVIRONMENT != "production":
        return

    issues: list[str] = []
    if settings.DEBUG:
        issues.append("DEBUG must be False in production.")
    if settings.SECRET_KEY.startswith("change-me-in-production"):
        issues.append("SECRET_KEY is still the default value — generate a long random secret.")
    if "*" in settings.CORS_ORIGINS:
        issues.append("CORS_ORIGINS is wide-open (*) — restrict to your frontend origin(s).")
    if issues:
        for msg in issues:
            logger.error("PRODUCTION GUARD: " + msg)
        raise RuntimeError(
            "Production startup guard failed — " + " ".join(issues)
        )
