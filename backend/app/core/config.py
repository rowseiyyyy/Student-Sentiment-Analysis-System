"""
Application configuration.

All values are loaded from environment variables (or a .env file in the
backend/ root). Sensible development defaults are provided so the project
runs out of the box, but every value should be overridden in production.
"""
import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Union

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

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
        "Sta. Rosa, Laguna using XGBoost (TF-DF), mDeBERTa and XLM-RoBERTa."
    )
    VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = Field(default="development")  # development | production
    DEBUG: bool = False

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
    # environment variables. The settings object must fail loudly if a
    # production deployment forgets to provide SECRET_KEY. Do not ship a
    # fallback secret in source control.
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    # Production must not ship with loopback or local development origins.
    # The deployment must supply CORS_ORIGINS explicitly from an environment
    # variable or secrets manager; no '*' and no localhost/loopback origins.
    # Accepts either a JSON array or a Render-style comma-separated string
    # (normalized to a list by the validator below).
    CORS_ORIGINS: Union[str, List[str]]
    FRONTEND_URL: str

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        """Normalize comma-separated CORS_ORIGINS strings into a list.

        Render/heroku-style env vars are plain strings, e.g.
        ``CORS_ORIGINS=https://a.vercel.app,https://b.vercel.app``. Declaring
        the field as Union[str, List[str]] avoids pydantic-settings' strict
        JSON decoding, and this validator guarantees the rest of the app
        always sees a clean List[str] (a stale env var replacing the
        allowlist is still honored — update the env var to fix it).
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # Minimum number of Likert questions that must be answered when a
    # submission includes ratings. Prevents API-level abuse where a
    # partial/empty ratings payload bypasses the frontend's "answer all"
    # enforcement. Should match (or exceed) the number of questions in
    # the evaluation form.
    LIKERT_MIN_QUESTIONS: int = 5

    # Database connection - can be set directly via DATABASE_URL env var for production
    # (e.g., mysql+pymysql://user:pass@host:3306/dbname or sqlite:///path/to/db.sqlite)
    # If not set, falls back to individual component settings below (for local dev).
    db_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")

    # Email / deployment configuration used for password resets and live frontend links.
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@example.com"
    SMTP_USE_TLS: bool = True

    DB_HOST: str
    DB_PORT: int
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_DRIVER: str = Field(default="mysql+pymysql")  # "mysql+pymysql" | "sqlite"

    # Temporary validation-only override: when set, all ML artifacts and the
    # validation database are redirected below this root without modifying the
    # default production paths.
    TEMP_VALIDATION_ROOT: Path | None = None
    VALIDATION_DB_NAME: str | None = None
    VALIDATION_SQLITE_PATH: Path | None = None

    @property
    def DATABASE_URL(self) -> str:
        # If DATABASE_URL is set via environment variable, use it directly
        # (allows overriding for production deployments). Keep the driver
        # family explicit and normalized to the installed PyMySQL dialect;
        # do not reinterpret the override into a MySQLdb-style URL token.
        if self.db_url_override:
            parsed_override = make_url(self.db_url_override)
            if self.DB_DRIVER == "mysql+pymysql" and parsed_override.drivername in {"mysql", "mysql+mysqldb", "mysql+pymysql"}:
                normalized_override = URL.create(
                    drivername="mysql+pymysql",
                    username=parsed_override.username,
                    password=parsed_override.password,
                    host=parsed_override.host,
                    port=parsed_override.port,
                    database=parsed_override.database,
                    query=None,
                )
                return normalized_override.render_as_string(hide_password=False)
            return self.db_url_override

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

        print("DEBUG DB_DRIVER passed to URL.create:", repr(self.DB_DRIVER), flush=True)
        print("DEBUG DB_USER:", repr(settings.DB_USER), flush=True)
        print("DEBUG DB_PASSWORD length:", len(settings.DB_PASSWORD), flush=True)
        _pw = settings.DB_PASSWORD
        _fp = hashlib.sha256(_pw.encode("utf-8")).hexdigest()[:12]
        print("DEBUG DB_PASSWORD length:", len(_pw), flush=True)
        print("DEBUG DB_PASSWORD sha256[:12]:", _fp, flush=True)
        print("DEBUG DB_PASSWORD has surrounding whitespace:", _pw != _pw.strip(), flush=True)
        print(
            "DEBUG DB_PASSWORD charset:",
            sorted({c for c in _pw if not (c.isalnum())}),
            flush=True,
        )

        print("DEBUG DB_HOST:", settings.DB_HOST, flush=True)
        print("DEBUG DB_PORT:", settings.DB_PORT, flush=True)
        print("DEBUG DB_NAME:", settings.DB_NAME, flush=True)
        print("DEBUG db_url_override is set:", bool(settings.db_url_override), flush=True)

        # Build SQLAlchemy DSNs using URL.create so username/password,
        # host, port, and database names are escaped the normal way and
        # credentials containing punctuation survive a round-trip.
        # Keep SQLite untouched and let the PyMySQL SSL handshake be
        # expressed in the engine's native `connect_args` object, which
        # matches the working raw `pymysql.connect(..., ssl={'ssl': {}})`
        # argument structure more closely than encoding `ssl-mode` into the
        # database URL string.
        parsed = URL.create(
            drivername=self.DB_DRIVER,
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=db_name,
            query=None,
        )
        return parsed.render_as_string(hide_password=False)

    # ------------------------------------------------------------------
    # JWT
    # ------------------------------------------------------------------
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days


    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_PREDICT: str = "20/minute"
    RATE_LIMIT_AUTH: str = "10/minute"

    @model_validator(mode="after")
    def validate_production_environment_shape(self) -> "Settings":
        """Fail fast with a clear message if production is configured
        without the required environment-backed public release variables.
        """
        if self.ENVIRONMENT != "production":
            return self

        required = [
            "SECRET_KEY",
            "CORS_ORIGINS",
            "FRONTEND_URL",
            "DB_HOST",
            "DB_PORT",
            "DB_USER",
            "DB_PASSWORD",
            "DB_NAME",
        ]
        missing = [name for name in required if not getattr(self, name, None)]
        if missing:
            raise ValueError(
                "Missing required production environment variables: " + ", ".join(missing)
            )

        if self.DEBUG:
            raise ValueError("DEBUG must be False in production mode.")

        cors = self.CORS_ORIGINS
        if isinstance(cors, str):
            cors_list = [origin.strip() for origin in cors.split(",") if origin.strip()]
        else:
            cors_list = list(cors)

        if not cors_list or any(origin == "*" for origin in cors_list):
            raise ValueError("CORS_ORIGINS must be restricted to the live frontend origin(s) in production.")
        if any(
            origin.lower().startswith((
                "http://localhost",
                "https://localhost",
                "http://127.0.0.1",
                "https://127.0.0.1",
                "http://0.0.0.0",
                "https://0.0.0.0",
            ))
            for origin in cors_list
        ):
            raise ValueError("CORS_ORIGINS must not include localhost or loopback origins in production.")

        frontend = self.FRONTEND_URL.lower() if self.FRONTEND_URL else ""
        if frontend.startswith((
            "http://localhost",
            "https://localhost",
            "http://127.0.0.1",
            "https://127.0.0.1",
            "http://0.0.0.0",
            "https://0.0.0.0",
        )):
            raise ValueError("FRONTEND_URL must not point to localhost in production.")

        return self

    # ------------------------------------------------------------------
    # ML / Model paths
    # ------------------------------------------------------------------
    ML_DIR: Path = BASE_DIR / "app" / "ml"
    DATASETS_DIR: Path = BASE_DIR / "app" / "datasets"

    # Active paths.
    # TF-DF GradientBoostedTrees model. This is deliberately separate from
    # the legacy native XGBoost artifacts; the formats are not interchangeable.
    XGB_MODEL_PATH: Path = ML_DIR / "xgb_tfdf"
    XGB_TFIDF_VECTORIZER_PATH: Path = ML_DIR / "tfidf_vectorizer_xgb.pkl"
    XGB_LABEL_ENCODER_PATH: Path = ML_DIR / "label_encoder_xgb.pkl"
    MDEBERTA_MODEL_PATH: Path = ML_DIR / "mdeberta_v3"
    XLM_ROBERTA_MODEL_PATH: Path = ML_DIR / "xlm_roberta_sentiment"

    MODEL_METADATA_PATH: Path = ML_DIR / "model_metadata.json"
    COMPARISON_RESULTS_PATH: Path = ML_DIR / "comparison_results.json"

    # General RoBERTa is fine-tuned on the actual student-feedback labels;
    # avoid treating a Twitter-domain sentiment checkpoint as a final model.
    XLM_ROBERTA_MODEL_NAME: str = "xlm-roberta-base"
    MDEBERTA_MODEL_NAME: str = "microsoft/mdeberta-v3-base"

    TRANSFORMER_DEVICE: str = "cpu"

    RANDOM_STATE: int = 42
    TEST_SIZE: float = 0.2

    # ------------------------------------------------------------------
    # Ensemble / evaluation
    # ------------------------------------------------------------------
    # Initial weights for the soft-vote ensemble. These are NOT claimed
    # to be optimal; they are starting values for the ensemble.
    ENSEMBLE_WEIGHTS: dict[str, float] = {
        "mDeBERTa": 0.4,
        "XLM-RoBERTa": 0.4,
        "XGBoost (TF-DF)": 0.2,
    }
    BOOTSTRAP_N_ITER: int = 1000
    BOOTSTRAP_ALPHA: float = 0.05
    BOOTSTRAP_SEED: int = 42

    # mDeBERTa fine-tune defaults (initial configuration; not validated
    # as optimal until a real labelled training/evaluation run).
    MDEBERTA_EPOCHS: int = 3
    MDEBERTA_BATCH_SIZE: int = 8
    MDEBERTA_LEARNING_RATE: float = 2e-5
    MDEBERTA_WEIGHT_DECAY: float = 0.01
    MDEBERTA_WARMUP_RATIO: float = 0.1
    MDEBERTA_MAX_SEQ_LENGTH: int = 256


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
        settings.XGB_MODEL_PATH = settings.ML_DIR / "xgb_tfdf"
        settings.XGB_TFIDF_VECTORIZER_PATH = settings.ML_DIR / "tfidf_vectorizer_xgb.pkl"
        settings.XGB_LABEL_ENCODER_PATH = settings.ML_DIR / "label_encoder_xgb.pkl"
        settings.MDEBERTA_MODEL_PATH = settings.ML_DIR / "mdeberta_v3"
        settings.XLM_ROBERTA_MODEL_PATH = settings.ML_DIR / "xlm_roberta_sentiment"
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
    wide-open or still pointed at local-only origins. Any failure logs the
    specific issue and raises RuntimeError so the process exits before
    serving traffic.
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
    if settings.SECRET_KEY in {
        "change-me-in-production-please-use-a-long-random-string",
        "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_1234567890",
    }:
        issues.append("SECRET_KEY is still the default value — generate a long random secret.")

    cors_origins = settings.CORS_ORIGINS
    if isinstance(cors_origins, str):
        cors_list = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]
    else:
        cors_list = list(cors_origins)

    if not cors_list:
        issues.append("CORS_ORIGINS is empty — set at least your production frontend origin(s).")
    if any(origin == "*" for origin in cors_list):
        issues.append("CORS_ORIGINS is wide-open (*) — restrict to your frontend origin(s).")
    if any(
        origin.lower().startswith((
            "http://localhost",
            "https://localhost",
            "http://127.0.0.1",
            "https://127.0.0.1",
            "http://0.0.0.0",
            "https://0.0.0.0",
        ))
        for origin in cors_list
    ):
        issues.append("CORS_ORIGINS still includes localhost or loopback origins in production.")
    if not settings.FRONTEND_URL or settings.FRONTEND_URL.lower().startswith((
        "http://localhost",
        "https://localhost",
        "http://127.0.0.1",
        "https://127.0.0.1",
        "http://0.0.0.0",
        "https://0.0.0.0",
    )):
        issues.append("FRONTEND_URL must point to the live public frontend, not localhost, in production.")

    if issues:
        for msg in issues:
            logger.error("PRODUCTION GUARD: " + msg)
        raise RuntimeError(
            "Production startup guard failed — " + " ".join(issues)
        )
