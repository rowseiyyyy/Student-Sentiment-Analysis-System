# Asiatech Sentiment Analysis API

**Sentiment Analysis of Student Feedback from Asiatech College of Sta. Rosa,
Laguna, Philippines Using Machine Learning Algorithms**

A production-ready FastAPI backend that classifies open-ended student
evaluation comments (Faculty, Staff, Payment, Facilities) into
**Positive / Neutral / Negative** sentiment, comparing four approaches —
**SVM (TF-IDF)**, **Naive Bayes (TF-IDF)**, **Logistic Regression (TF-IDF)**,
and **Multilingual MiniLM** — with Multilingual MiniLM serving every live
prediction.

## Quick Start (Windows)

```bat
cd backend
.venv\Scripts\activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
python run.py
```

Or use the launcher scripts (they put `backend/` on `sys.path` for you):

```bat
:: from inside backend/
..\.venv\Scripts\python.exe run.py

:: from the project root (asiatech-sentiment-backend/)
python run.py
```

> **Important:** the application entry point is `backend/main.py`, not
> `app/main.py`. Run `uvicorn main:app …` from the `backend/` directory.
> Running `uvicorn app.main:app …` will fail with
> `ModuleNotFoundError: No module named 'app'`.

## Table of Contents

1. [Features](#features)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Installation Guide](#installation-guide)
5. [Running the Application](#running-the-application)
6. [Training the Models](#training-the-models)
7. [API Overview](#api-overview)
8. [Developer Guide](#developer-guide)
9. [Deployment Guide](#deployment-guide)
10. [Testing](#testing)
11. [Documentation](#documentation)

---

## Features

- **Four-approach sentiment pipeline**: SVM, Naive Bayes, and Logistic
  Regression over TF-IDF features, plus **Multilingual MiniLM**
  (HuggingFace Transformers, quantized ONNX) — trained/evaluated on
  identical splits.
- **Research mode**: `/ml/import-results` records training metrics from the
  Colab notebook — accuracy, precision, recall, F1,
  macro F1, weighted F1, confusion matrices, classification reports,
  training time, inference time, and memory usage for every model.
- **Production mode**: **Multilingual MiniLM** is the only live model —
  every new student evaluation is officially scored with it. The classical
  TF-IDF models are research baselines and are never used for live
  inference (no fallback; a failed MiniLM load returns HTTP 503).
- **Full CRUD + analytics** for evaluations, with role-based access
  control (student vs. administrator), JWT auth, rate limiting, and CSV
  export.
- **Admin panel API**: dataset upload/validation, metrics import, model
  comparison table, confusion matrix, classification report, rollback to
  a previous run, and downloadable MiniLM artifacts.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend framework | FastAPI, Pydantic v2, Uvicorn |
| ORM / Migrations | SQLAlchemy 2.0, Alembic |
| Database | MySQL (PyMySQL driver) |
| Auth | JWT (python-jose), bcrypt (passlib) |
| ML / NLP | scikit-learn, HuggingFace Transformers, ONNX Runtime, NLTK, spaCy |
| Data | Pandas, NumPy, Joblib |
| Visualization (data prep) | Plotly, Matplotlib |
| Docs | Swagger / OpenAPI (auto-generated at `/docs`) |

---

## Project Structure

```text
backend/
├── app/
│   ├── api/                 # FastAPI routers (auth, evaluation, prediction, analytics, ml)
│   ├── core/                # config, database, security, rate limiter
│   ├── models/               # SQLAlchemy ORM models
│   ├── schemas/               # Pydantic request/response schemas
│   ├── services/               # business logic / ML services
│   ├── utils/                   # logging, helpers
│   ├── ml/                        # trained model artifacts (.pkl, metadata)
│   └── datasets/                   # uploaded / sample CSV datasets
├── alembic/                          # DB migrations
├── scripts/
│   └── train_models.py                # standalone CLI training script
├── tests/                               # Pytest suite
├── docs/
│   ├── DIAGRAMS.md                        # ER / architecture / sequence diagrams
│   └── postman_collection.json             # Postman collection
├── main.py                                  # FastAPI application entry point
├── requirements.txt
├── alembic.ini
└── .env.example
```

---

## Installation Guide

### Prerequisites

- Python 3.11+ (recommended; the app runs on 3.11 – 3.12)
- MySQL 8.0+ (running instance, with a database created for this project)
- `pip` and (recommended) a virtual environment tool

### Steps

```bash
# 1. Clone / unzip the project, then enter the backend directory
cd backend

# 2. Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Download required NLTK data (also auto-downloaded on first run)
python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('stopwords'); nltk.download('wordnet'); nltk.download('omw-1.4')"

# 5. (Optional but recommended) Download the spaCy English model
python -m spacy download en_core_web_sm

# 6. Create your MySQL database
mysql -u root -p -e "CREATE DATABASE asiatech_sentiment_db CHARACTER SET utf8mb4;"

# 7. Configure environment variables
cp .env.example .env
# then edit .env with your real DB credentials and a strong SECRET_KEY
# for production, do not leave DEBUG=true or localhost in CORS_ORIGINS

# 8. Apply database migrations
alembic upgrade head
```

### Production launch notes

- Set `ENVIRONMENT=production` and `DEBUG=false` in the deployed environment.
- Set `APP_RELOAD=false` for production; reload mode is only for local development.
- Restrict `CORS_ORIGINS` to the exact public frontend domain(s).
- Run the backend with Gunicorn instead of the debug server for public deployment.
- Keep secrets in environment variables or a managed secrets store, not in source control.

> In `ENVIRONMENT=development` mode, `main.py` also calls
> `Base.metadata.create_all()` on startup as a convenience, so you can skip
> Alembic locally. **Always use Alembic in production.**

---

## Running the Application

From the `backend/` directory:

```bash
venv\Scripts\activate        # Windows
# or: source venv/bin/activate   # Linux/macOS
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Shortcut — from the project root (no manual venv activation or `cd` needed):

```bash
python run.py
```

> The module string is `main:app` — the entry point lives at
> `backend/main.py`. Do **not** use `app.main:app` (there is no
> `backend/app/main.py`); that will raise
> `ModuleNotFoundError: No module named 'app'`.

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI schema: <http://localhost:8000/openapi.json>
- Health check: <http://localhost:8000/health>

Seed admin credentials (development only):

```json
{
  "email": "admin@gmail.com",
  "password": "admin123"
}
```

---

## Training the Models

The system ships with a labeled sample dataset at
`app/datasets/sample_feedback.csv` (60 rows across all 4 categories and 3
sentiment classes) so you can exercise the full pipeline immediately.

There is **no `/ml/train` endpoint** — training runs outside the API
(Colab notebook or the CLI script) and the resulting metrics are imported
back through `/ml/import-results`. Only **Multilingual MiniLM** serves live
inference; the classical approaches are research/comparison entries.

### Option A — Colab notebook + metrics import (recommended)

1. Register an administrator account:

   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"full_name":"Admin","email":"admin@asiatech.edu.ph","password":"AdminPass123","role":"administrator"}'
   ```

2. Log in and grab the `access_token`.

3. Upload a dataset (optional; used for dataset versioning/validation):

   ```bash
   curl -X POST http://localhost:8000/api/v1/ml/dataset/upload \
     -H "Authorization: Bearer <TOKEN>" \
     -F "file=@app/datasets/sample_feedback.csv"
   ```

4. Run the Colab training notebook and export its metrics JSON, then import it:

   ```bash
   curl -X POST "http://localhost:8000/api/v1/ml/import-results?set_production=Multilingual%20MiniLM" \
     -H "Authorization: Bearer <TOKEN>" \
     -F "metrics_json=@metrics.json"
   ```

5. Inspect results: `GET /api/v1/ml/performance`,
   `GET /api/v1/ml/confusion-matrix?algorithm=SVM`,
   `GET /api/v1/ml/classification-report?algorithm=Multilingual%20MiniLM`, etc.

#### Metrics JSON format (the `metrics_json` file)

`POST /api/v1/ml/import-results` (administrator token) accepts a single
`multipart/form-data` file field named **`metrics_json`** with a **2 MB** hard
cap. `set_production` is an optional **query parameter**, not a form field. A
complete, ready-to-use example ships at
[`docs/sample_metrics_export.json`](docs/sample_metrics_export.json), and you
can dry-run any export before uploading it:

```bash
python scripts/_validate_colab_export.py "path/to/dashboard_export.json"
```

Two payload shapes are accepted.

**Shape A - Colab `dashboard_export.json`** (models nested under `models`):

```json
{
  "label_map": { "0": "Negative", "1": "Neutral", "2": "Positive" },
  "recommended_production_model": "minilm",
  "models": {
    "svm": {
      "accuracy": 0.908,
      "precision_weighted": 0.9081,
      "recall_weighted": 0.908,
      "weighted_f1": 0.908,
      "macro_f1": 0.899,
      "per_class": {
        "Negative": { "precision": 0.9642, "recall": 0.9586, "f1": 0.9614, "support": 870 },
        "Neutral": { "precision": 0.8395, "recall": 0.8333, "f1": 0.8364, "support": 546 },
        "Positive": { "precision": 0.8944, "recall": 0.9041, "f1": 0.8992, "support": 834 }
      },
      "confusion_matrix": [[834, 20, 16], [22, 455, 69], [14, 62, 758]],
      "training_time_seconds": 12.4,
      "inference_time_ms": 0.9,
      "memory_usage_mb": 41.2,
      "hyperparameters": { "C": 1.0, "kernel": "linear" }
    },
    "naive_bayes": { },
    "logistic_regression": { },
    "minilm": { }
  }
}
```

**Shape B - already-flat rows** (what the admin UI and the tests send):

```json
{
  "rows": {
    "SVM": { "accuracy": 0.90, "precision": 0.90, "recall": 0.90, "f1_score": 0.90, "macro_f1": 0.89, "weighted_f1": 0.90 },
    "Naive Bayes": { },
    "Logistic Regression": { },
    "Multilingual MiniLM": { }
  },
  "best_model": "Multilingual MiniLM"
}
```

Top-level keys:

| Key | Required | Notes |
| --- | --- | --- |
| `models` | Shape A | Object of `model_key -> metrics`. Read whenever it is an object. |
| `rows` | Shape B | Flat `approach -> metrics` map; only read when `models` is absent. Keys must already be canonical (or an accepted alias). |
| `label_map` | Optional (Shape A only) | `{"0": "Negative", ...}` (the **values** are used) or a list of names. Omitted -> `Negative, Neutral, Positive`. |
| `recommended_production_model` / `best_model` | Optional | Report-only recommendation; never changes which model is live. |

`models` keys are resolved case- and punctuation-insensitively
(`colab_key_to_approach`):

| Export key (normalised) | Canonical approach |
| --- | --- |
| `svm`, `svc`, `supportvectormachine` | SVM |
| `naivebayes`, `nb`, `multinomialnb` | Naive Bayes |
| `logisticregression`, `logreg`, `lr` | Logistic Regression |
| anything containing `minilm` (`minilm`, `multilingualminilm`, ...) | Multilingual MiniLM |
| anything else | skipped, with a warning in the log |

Per-model fields (`_normalize_colab_model`):

| Field | Notes |
| --- | --- |
| `accuracy` | Stored as-is. |
| `precision_weighted` (fallback `precision`) | Fills the `precision` column. |
| `recall_weighted` (fallback `recall`) | Fills the `recall` column. |
| `weighted_f1` (fallback `f1_score`) | Fills `f1_score`; only `weighted_f1` fills the `weighted_f1` column. |
| `macro_f1` | Stored as-is. |
| `per_class.<label>.{precision,recall,f1,support}` | Builds the classification report. Use `f1` here (not `f1-score`), and `<label>` must match the resolved label names. |
| `confusion_matrix` | 3x3 `list[list[int]]` in `Negative, Neutral, Positive` order; stored verbatim and labelled server-side, so order matters. Feeds `GET /ml/confusion-matrix`. |
| `training_time_seconds`, `inference_time_ms`, `memory_usage_mb` | Optional; stored as-is. |
| `hyperparameters` | Optional free-form object. |

Things worth knowing:

- `classification_report` is **not** a field you send - the server builds it
  from `per_class`.
- `set_production` can never promote a classical model. The importer always
  pins `is_production_model` to Multilingual MiniLM and returns the
  best-scoring import as `recommended_model` instead.
- If no key resolves to an approved approach the request fails with **422**
  (`No approved approaches found in the metrics payload.`).
- The import records metrics only - it never uploads or replaces the live
  MiniLM weights (those are pulled from the Hugging Face Hub at boot).

| Response | Meaning |
| --- | --- |
| `200` | `{message, imported_algorithms, production_model, recommended_model, artifacts_updated}` (`artifacts_updated` is currently always `[]`) |
| `400` | Body is not valid JSON |
| `403` | Caller is not an administrator |
| `413` | File larger than 2 MB |
| `422` | No approved approach found in the payload |

### Option B — via the CLI script

```bash
python scripts/train_models.py --dataset app/datasets/sample_feedback.csv
```

The full pipeline fits the TF-IDF classical models (SVM, Naive Bayes,
Logistic Regression) and evaluates Multilingual MiniLM on the same splits,
writing the metrics artifacts that the API/Admin panel reads.

After training, `app/ml/comparison_results.json` and
`app/ml/model_metadata.json` are updated. All subsequent `POST /evaluation`
and `POST /predict` calls use **Multilingual MiniLM** for the **official**
prediction.

---

## API Overview

Full interactive documentation is available at `/docs`. Summary:

| Group | Endpoints |
| --- | --- |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`, `GET/PUT /auth/me/profile`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Evaluations | `POST /evaluation`, `GET /evaluation`, `GET /evaluation/{id}`, `DELETE /evaluation/{id}` (admin), `POST /evaluation/bulk-delete`, `GET /evaluation/config` |
| Prediction | `POST /predict` |
| Analytics | `GET /analytics/overall`, `/category`, `/monthly`, `/daily`, `/terms`, `/term-comparison`, `/word-frequency`, `/top-complaints`, `/top-appreciations`, `/export/csv` |
| Imports (Admin) | `POST /imports/evaluations` |
| ML (Admin) | `POST /ml/dataset/upload`, `POST /ml/import-results`, `GET /ml/models`, `GET /ml/performance`, `GET /ml/confusion-matrix`, `GET /ml/classification-report`, `POST /ml/rollback`, `GET /ml/models/{algorithm}/download` |
| Action updates | `GET /action-updates/public`, `GET/POST /action-updates`, `PATCH/DELETE /action-updates/{post_id}` |
| Voice notes | `POST /voice-notes`, `GET /voice-notes`, `GET /voice-notes/stats`, `DELETE /voice-notes/{note_id}` |

All routes are versioned under `/api/v1`. A ready-to-import
[Postman collection](docs/postman_collection.json) covering every endpoint
is included.

---

## Developer Guide

### Architecture

The backend follows a **service-layer architecture**:

- **`api/`** — thin FastAPI routers: validate input via Pydantic, call a
  service, return a response schema. No business logic here.
- **`services/`** — all business logic, including ML training/inference,
  lives here. Services are framework-agnostic and unit-testable.
- **`models/`** — SQLAlchemy ORM models (persistence layer).
- **`schemas/`** — Pydantic models for request/response validation
  (separate from ORM models, per SOLID's Single Responsibility Principle).
- **`core/`** — cross-cutting concerns: config, DB session, security, rate
  limiting.

### Adding a new endpoint

1. Define/extend a Pydantic schema in `app/schemas/`.
2. Add business logic to the relevant service in `app/services/` (or
   create a new service module).
3. Add a route in the matching router under `app/api/`.
4. Add a test in `tests/`.

### Preprocessing pipeline

`app/services/preprocessing.py` exposes two functions:

- `clean_for_classical(text)` — aggressive cleaning (lowercase, strip
  URLs/HTML/emojis/punctuation/numbers, expand contractions, tokenize,
  remove stopwords, lemmatize) used by the classical models before TF-IDF.
- `clean_for_transformer(text)` — light cleaning only (URLs/HTML/emojis
  removed); case, stopwords and grammar are preserved so the transformer
  contextual embeddings remain meaningful.

### Model comparison logic

`app/services/training.py::run_full_training` is the single source of
truth for how models are trained/evaluated and how the production model
is recorded (highest **weighted F1** across identical test splits). If
you need a different selection criterion (e.g. macro F1, or a minimum
accuracy threshold), that's the function to change.

### Database migrations

```bash
# After changing a model in app/models/:
alembic revision --autogenerate -m "describe your change"
alembic upgrade head
```

---

## Deployment Guide

### Environment variables

Set the following in production (never commit real secrets):

- `ENVIRONMENT=production`
- `SECRET_KEY` — a long, random value (`openssl rand -hex 32`)
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
- `CORS_ORIGINS` — restrict to your actual frontend domain(s)
- `HF_TOKEN` — Hugging Face read token for the private
  `HF_MINILM_REPO` (`rowseiy/minilm-sentiment`) that serves the live model
- `TRANSFORMER_DEVICE=cuda` if a GPU is available (falls back to `cpu` otherwise)
- `ENABLE_MINILM_INFERENCE` / `MINILM_MIN_RAM_MB` — the memory guard that
  protects the free-tier instance from MiniLM OOM crashes

### Recommended production checklist

1. Run `alembic upgrade head` as part of your deploy pipeline — do **not**
   rely on `Base.metadata.create_all()` (that only runs when
   `ENVIRONMENT=development`).
2. Serve with a process manager, e.g.:

   ```bash
   gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
   ```

3. Put a reverse proxy (Nginx / Traefik) in front for TLS termination and
   static file caching.
4. Pre-warm the Multilingual MiniLM ONNX model at startup (the first request
   will otherwise pay the load cost) if desired.
5. Persist `app/ml/` and `app/datasets/` on a volume that survives
   deployments/restarts (or move them to object storage and adjust
   `app/core/config.py` paths accordingly).
6. Configure log shipping from `logs/app.log` (rotated via Loguru) to your
   observability stack.
7. Rate limits (`slowapi`) are in-memory by default; for multi-instance
   deployments back them with Redis (`slowapi` supports a Redis storage
   backend via `storage_uri`).

### Docker (example)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_sm \
    && python -c "import nltk; nltk.download('punkt'); nltk.download('punkt_tab'); nltk.download('stopwords'); nltk.download('wordnet'); nltk.download('omw-1.4')"
COPY . .
EXPOSE 8000
CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000"]
```

---

## Testing

```bash
pytest -v
```

The test suite uses an in-memory SQLite database (via dependency
override) so it never touches your real MySQL instance. ML-heavy
endpoints that would otherwise require trained model artifacts are
tested with mocked service calls where appropriate; dataset validation,
auth, RBAC, and analytics aggregation logic are tested directly.

---

## Documentation

- **Swagger / OpenAPI**: auto-generated, live at `/docs` and `/openapi.json`.
- **[docs/DIAGRAMS.md](docs/DIAGRAMS.md)**: ER diagram, architecture
  diagram, and sequence diagrams (Mermaid format).
- **[docs/postman_collection.json](docs/postman_collection.json)**:
  importable Postman collection for every endpoint.
- **Database schema**: see `app/models/` for ORM definitions and
  `alembic/versions/0001_initial_schema.py` for the canonical DDL.
- **[docs/sample_metrics_export.json](docs/sample_metrics_export.json)**: a
  validated example of the `metrics_json` payload accepted by
  `POST /ml/import-results` (format documented under
  [Training the Models](#training-the-models)).
- **`scripts/_validate_colab_export.py`**: dry-run any Colab export against the
  active import logic before uploading it (no DB or artifact writes).
