"""
Application configuration.

All values are loaded from environment variables (or a .env file in the
backend/ root). Sensible development defaults are provided so the project
runs out of the box, but every value should be overridden in production.
"""
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
        "Sta. Rosa, Laguna using SVM, Naive Bayes, Logistic Regression and Multilingual MiniLM."
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

    # ------------------------------------------------------------------
    # Analytics thresholds
    # ------------------------------------------------------------------
    # A prediction whose confidence is below this is counted as
    # "low confidence" by the Overview health snapshot. 0.5 = 50%: the model
    # was no more sure than a coin flip, so the submission is worth a human
    # look rather than being trusted as-is. Kept configurable because the
    # right cut-off depends on the deployed model's calibration.
    LOW_CONFIDENCE_THRESHOLD: float = 0.5

    # ------------------------------------------------------------------
    # Academic calendar (Analytics)
    # ------------------------------------------------------------------
    # The evaluations table stores only the submission timestamp — it has no
    # grading-period / academic-term column — so the "Sentiment by Academic
    # Term" chart buckets submissions by the MONTH each was submitted in,
    # using the calendar below.
    #
    # Default: the institution's real grading calendar. Each semester has
    # four single-month grading periods, so no month is shared between two
    # terms and the chart plots exactly the eight defined periods:
    #   Term 1 (1st semester): Prelim = July,  Midterm = August,
    #                          Prefinal = September, Finals = October
    #   Term 2 (2nd semester): Prelim = February, Midterm = March,
    #                          Prefinal = April, Finals = May
    # November, December, January and June fall outside every grading period
    # (semestral break / enrollment), so a submission from one of those
    # months is deliberately excluded from the term chart rather than being
    # guessed into the nearest period. That is also why the x-axis shows
    # eight periods and not twelve months.
    #
    # Term names double as the chart's x-axis labels and bucket keys, so they
    # must be unique: "Prelim" (etc.) repeats in both semesters, hence each
    # entry is prefixed with the term it belongs to.
    #
    # Override from the environment to match a changed school calendar, e.g.
    #   ACADEMIC_TERM_MONTHS='[{"term": "Term 1 Prelim", "months": [7]}, {"term": "Term 1 Midterm", "months": [8]}]'
    # Month numbers are 1-12 (1 = January). List order defines the order the
    # terms appear in on the chart (Term 1 first, then Term 2). A month may
    # appear in only one period; any month left out simply produces no term
    # bucket, so a submission in that month is not counted towards any term.
    ACADEMIC_TERM_MONTHS: List[dict[str, Any]] = [
        {"term": "Term 1 Prelim", "months": [7]},
        {"term": "Term 1 Midterm", "months": [8]},
        {"term": "Term 1 Prefinal", "months": [9]},
        {"term": "Term 1 Finals", "months": [10]},
        {"term": "Term 2 Prelim", "months": [2]},
        {"term": "Term 2 Midterm", "months": [3]},
        {"term": "Term 2 Prefinal", "months": [4]},
        {"term": "Term 2 Finals", "months": [5]},
    ]

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

    DB_HOST: str = ""
    DB_PORT: int = 3306
    DB_USER: str = ""
    DB_PASSWORD: str = ""
    DB_NAME: str = ""
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

    # Active paths (classical research models: SVM / Naive Bayes / Logistic
    # Regression — each with its own fitted TF-IDF vectorizer).
    SVM_MODEL_PATH: Path = ML_DIR / "svm_model.pkl"
    SVM_VECTORIZER_PATH: Path = ML_DIR / "tfidf_vectorizer_svm.pkl"
    NAIVE_BAYES_MODEL_PATH: Path = ML_DIR / "naive_bayes_model.pkl"
    NAIVE_BAYES_VECTORIZER_PATH: Path = ML_DIR / "tfidf_vectorizer_naive_bayes.pkl"
    LOGREG_MODEL_PATH: Path = ML_DIR / "logreg_model.pkl"
    LOGREG_VECTORIZER_PATH: Path = ML_DIR / "tfidf_vectorizer_logreg.pkl"

    MODEL_METADATA_PATH: Path = ML_DIR / "model_metadata.json"
    COMPARISON_RESULTS_PATH: Path = ML_DIR / "comparison_results.json"

    # ------------------------------------------------------------------
    # HuggingFace Hub (private model repos)
    # ------------------------------------------------------------------
    # Token used to authenticate against the private HuggingFace Hub repos
    # below. Populate HF_TOKEN in the environment / .env file. When empty, the
    # startup downloader (services/hub_downloader.py) skips hub downloads —
    # useful when the artifacts are already present locally (e.g. the
    # pre-committed app/ml/ files in this repo, or dev/test environments).
    HF_TOKEN: str = ""

    # Private repos holding the tuned sentiment artifacts. The downloader pulls
    # these into the corresponding app/ml/ paths at startup only when the local
    # files are missing, using HF_TOKEN to authenticate.
    HF_MINILM_REPO: str = "rowseiy/minilm-sentiment"

    # Approved approach to register as production on a fresh database when the
    # models are pulled from the private hub at startup. Must match an approved
    # approach name (see training.APPROACH_TO_ALGORITHM). The live production
    # sentiment model is Multilingual MiniLM — small enough to serve within the
    # free-tier RAM budget.
    HF_PRODUCTION_MODEL: str = "Multilingual MiniLM"

    MINILM_ONNX_FILE: str = "model.onnx"

    # Multilingual MiniLM — the ONLY live production model. Trained in Colab
    # and served from its quantized ONNX artifact (see minilm_service).
    MINILM_MODEL_NAME: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    MINILM_MODEL_PATH: Path = ML_DIR / "minilm_sentiment"
    MINILM_MAX_SEQ_LENGTH: int = 128

    # Live inference for MiniLM is memory-gated. Measured footprint of this
    # ONNX path (app baseline + fast tokenizer + the 119 MB quantized session)
    # is ~570-640 MB RSS, so a 512 MB instance (e.g. Render's free tier) cannot
    # host it: the worker gets OOM-killed mid-request and the browser reports
    # "Unable to connect to the server. Please ensure the backend is running."
    # When the host reports less than MINILM_MIN_RAM_MB of memory, live
    # inference is refused — MiniLM is the ONLY live model, so prediction
    # requests then fail with a clean 503 instead of silently serving a
    # different model.
    # ENABLE_MINILM_INFERENCE=false disables MiniLM everywhere (also 503);
    # set MINILM_MIN_RAM_MB=0 to disable the memory guard entirely.
    ENABLE_MINILM_INFERENCE: bool = True
    MINILM_MIN_RAM_MB: int = 900

    # Optional override of the host memory limit the guard above compares
    # against. Platforms that expose no usable cgroup limit can set this to
    # make the decision deterministic (e.g. MINILM_HOST_RAM_MB=512 on a 512 MB
    # instance). Unset -> the limit is auto-detected; 0 -> unlimited.
    MINILM_HOST_RAM_MB: int | None = None

    TRANSFORMER_DEVICE: str = "cpu"

    RANDOM_STATE: int = 42
    TEST_SIZE: float = 0.2

    # ------------------------------------------------------------------
    # Evaluation / bootstrap
    # ------------------------------------------------------------------
    BOOTSTRAP_N_ITER: int = 1000
    BOOTSTRAP_ALPHA: float = 0.05
    BOOTSTRAP_SEED: int = 42

    # Classical model defaults (SVM / Naive Bayes / Logistic Regression).
    SVM_C: float = 1.0
    NAIVE_BAYES_ALPHA: float = 1.0
    LOGREG_C: float = 1.0
    LOGREG_MAX_ITER: int = 1000

    # Shared transformer fine-tune defaults (used by the MiniLM training path).
    MINILM_EPOCHS: int = 3
    MINILM_BATCH_SIZE: int = 8
    MINILM_LEARNING_RATE: float = 2e-5
    MINILM_WEIGHT_DECAY: float = 0.01
    MINILM_WARMUP_RATIO: float = 0.1

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
        settings.SVM_MODEL_PATH = settings.ML_DIR / "svm_model.pkl"
        settings.SVM_VECTORIZER_PATH = settings.ML_DIR / "tfidf_vectorizer_svm.pkl"
        settings.NAIVE_BAYES_MODEL_PATH = settings.ML_DIR / "naive_bayes_model.pkl"
        settings.NAIVE_BAYES_VECTORIZER_PATH = settings.ML_DIR / "tfidf_vectorizer_naive_bayes.pkl"
        settings.LOGREG_MODEL_PATH = settings.ML_DIR / "logreg_model.pkl"
        settings.LOGREG_VECTORIZER_PATH = settings.ML_DIR / "tfidf_vectorizer_logreg.pkl"
        settings.MINILM_MODEL_PATH = settings.ML_DIR / "minilm_sentiment"
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
