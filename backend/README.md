# Asiatech Sentiment Analysis API

**Sentiment Analysis of Student Feedback from Asiatech College of Sta. Rosa,
Laguna, Philippines Using Machine Learning Algorithms**

A production-ready FastAPI backend that classifies open-ended student
evaluation comments (Faculty, Staff, Payment, Facilities) into
**Positive / Neutral / Negative** sentiment, comparing three algorithms —
**SVM**, **Random Forest**, and **BERT** — and automatically promoting the
best-performing model to production.

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
python run.pypuy
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

- **Three-model sentiment pipeline**: SVM (TF-IDF + calibrated LinearSVC),
  Random Forest (TF-IDF), and BERT (`cardiffnlp/twitter-roberta-base-sentiment`
  via HuggingFace Transformers), trained/evaluated on identical splits.
- **Research mode**: `/ml/train` trains SVM + Random Forest and evaluates
  BERT on the same held-out data, records accuracy, precision, recall, F1,
  macro F1, weighted F1, confusion matrices, classification reports,
  training time, inference time, and memory usage for every model.
- **Production mode**: the highest-weighted-F1 model is automatically
  promoted; every new student evaluation is officially scored using that
  model, while all three models' raw predictions are still stored for
  ongoing research/comparison.
- **Full CRUD + analytics** for evaluations, with role-based access
  control (student vs. administrator), JWT auth, rate limiting, and CSV
  export.
- **Admin panel API**: dataset upload/validation, train/retrain, model
  comparison table, confusion matrix, classification report, rollback to
  a previous model, and downloadable `.pkl` artifacts.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI, Pydantic v2, Uvicorn |
| ORM / Migrations | SQLAlchemy 2.0, Alembic |
| Database | MySQL (PyMySQL driver) |
| Auth | JWT (python-jose), bcrypt (passlib) |
| ML / NLP | scikit-learn, HuggingFace Transformers, PyTorch, NLTK, spaCy |
| Data | Pandas, NumPy, Joblib |
| Visualization (data prep) | Plotly, Matplotlib |
| Docs | Swagger / OpenAPI (auto-generated at `/docs`) |

---

## Project Structure

```
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

- Python 3.12+
- MySQL 8.0+ (running instance, with a database created for this project)
- `pip` and (recommended) a virtual environment tool

### Steps

```bash
# 1. Clone / unzip the project, then enter the backend directory
cd backend

# 2. Create and activate a virtual environment
python3.12 -m venv venv
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

# 8. Apply database migrations
alembic upgrade head
```

> In `ENVIRONMENT=development` mode, `main.py` also calls
> `Base.metadata.create_all()` on startup as a convenience, so tables  you skip Alembic locally. **Always use Alembic in
> production.**

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

- Swagger UI: http://localhost:8000/docs
- login with: {
  "email": "admin@gmail.com",
  "password": "admin123"
}
- ReDoc: **http://localhost:8000/redoc**
- OpenAPI schema: **http://localhost:8000/openapi.json**
- Health check: **http://localhost:8000/health**

---

## Training the Models

The system ships with a labeled sample dataset at
`app/datasets/sample_feedback.csv` (60 rows across all 4 categories and 3
sentiment classes) so you can exercise the full pipeline immediately.

### Option A — via the API (recommended, matches the Admin Panel flow)

1. Register an administrator account:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"full_name":"Admin","email":"admin@asiatech.edu.ph","password":"AdminPass123","role":"administrator"}'
   ```
2. Log in and grab the `access_token`.
3. Upload a dataset:
   ```bash
   curl -X POST http://localhost:8000/api/v1/ml/dataset/upload \
     -H "Authorization: Bearer <TOKEN>" \
     -F "file=@app/datasets/sample_feedback.csv"
   ```
4. Train:
   ```bash
   curl -X POST http://localhost:8000/api/v1/ml/train \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"dataset_filename":"<returned_filename>","n_estimators":300}'
   ```
5. Inspect results: `GET /api/v1/ml/performance`,
   `/ml/confusion-matrix?algorithm=SVM`, `/ml/classification-report?algorithm=BERT`, etc.

### Option B — via the CLI script

```bash
python scripts/train_models.py --dataset app/datasets/sample_feedback.csv
```

Add `--skip-bert` to train only the classical models faster (BERT
inference on a full held-out split is the slowest step, especially on
CPU).

After training, the best model (by weighted F1) is automatically flagged
`is_production_model = true` in `training_history`, and
`app/ml/comparison_results.json` / `app/ml/model_metadata.json` are
updated. All subsequent `POST /evaluation` and `POST /predict` calls use
that model for the **official** prediction.

---

## API Overview

Full interactive documentation is available at `/docs`. Summary:

| Group | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| Evaluations | `POST /evaluation`, `GET /evaluation`, `GET /evaluation/{id}`, `DELETE /evaluation/{id}` (admin) |
| Prediction | `POST /predict` |
| Analytics | `GET /analytics/overall`, `/category`, `/monthly`, `/daily`, `/word-frequency`, `/top-complaints`, `/top-appreciations`, `/export/csv` |
| ML (Admin) | `POST /ml/dataset/upload`, `POST /ml/train`, `POST /ml/retrain`, `GET /ml/models`, `GET /ml/performance`, `GET /ml/confusion-matrix`, `GET /ml/classification-report`, `POST /ml/rollback`, `GET /ml/models/{algorithm}/download` |

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
  remove stopwords, lemmatize) used by SVM & Random Forest before TF-IDF.
- `clean_for_bert(text)` — light cleaning only (URLs/HTML/emojis removed);
  case, stopwords and grammar are preserved so BERT's contextual
  embeddings remain meaningful.

### Model comparison logic

`app/services/training.py::run_full_training` is the single source of
truth for how models are trained/evaluated and how the production model
is selected (highest **weighted F1** across identical test splits). If
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
- `BERT_DEVICE=cuda` if a GPU is available (falls back to `cpu` otherwise)

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
4. Pre-warm the BERT model at startup (first request will otherwise pay
   the HuggingFace download/load cost) by calling
   `bert_service._load_pipeline()` once during app startup if desired.
5. Persist `app/ml/*.pkl` and `app/datasets/` on a volume that survives
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
