# Production deployment guide

This project is now set up to run with production-safe defaults, but the actual hosting environment still needs a few real values before deployment.

> For the full picture (layers, ports, data model, request flows) see
> `SYSTEM_ARCHITECTURE.md`. Sections §8 (PuTTY session setup, tunnels, Docker /
> systemd / nginx runbook) and §11 (post-deployment verification checklist) cover
> deploying this backend on a Linux host while administering it through PuTTY.

## 1. Required production environment variables

Create a real deployment environment or `.env` file from the template in `backend/.env.example` and replace placeholders with the live values.

Required values:

- `ENVIRONMENT=production`
- `DEBUG=false`
- `SECRET_KEY=<a long random secret>`
- `DB_HOST=<production database host>`
- `DB_PORT=3306`
- `DB_USER=<db user>`
- `DB_PASSWORD=<strong db password>`
- `DB_NAME=asiatech_sentiment_db`
- `CORS_ORIGINS=https://your-frontend-domain.example`
- `APP_RELOAD=false`

## 2. Production database setup

- Provision a MySQL 8+ database.
- Create the schema so it matches the project migrations.
- Run:

```bash
cd backend
alembic upgrade head
```

- Require backups and a restore test.

## 3. Production backend startup

Use a real production web server, not the dev reload server.

Recommended command:

```bash
cd backend
gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --timeout 300 --bind 0.0.0.0:8000
```

CSV imports score each submitted comment with the live model and can take
longer than Gunicorn's 30-second default. Keep nginx's upstream timeout at
least as long as the Gunicorn timeout in the API proxying location:

```nginx
proxy_read_timeout 300s;
proxy_send_timeout 300s;
```

> **Worker count vs. RAM.** The live sentiment model (mBERT Hybrid) loads a full
> fp32 encoder into every Gunicorn worker: ~1.6–2.0 GB RSS each. The command
> above therefore needs a host with **>= 4 GB** of RAM. On a 2 GB host, run a
> single worker instead (`--workers 1`). If the host reports less than
> `MBERT_MIN_RAM_MB` (default `2048`), the memory guard refuses inference and
> every prediction returns 503 — there is no fallback model.
>
> The mBERT artifacts (~711 MB) are not committed to git; on a fresh host set
> `HF_TOKEN` in `backend/.env` so the startup downloader can fetch them, then
> confirm `GET /ready` reports `"models": "ready"`.

## 4. HTTPS and CORS

- Keep HTTPS forced in production.
- Configure `CORS_ORIGINS` to the exact frontend origin only.
- Do not use wildcard `*` origins for public deployment.

## 5. Auth and reset flow

- Keep JWT secret in environment variables or a secrets manager.
- Do not expose password-reset tokens in API responses in production.
- Use a real mail provider for password reset emails.

## 6. Model and inference setup

- Verify model files in `backend/app/ml` are present and versioned.
- Keep model files in a persistent volume or deployment artifact.
- Confirm the inference runtime matches the model format and dependencies.

## 7. Monitoring and health checks

Use at minimum:

- `/health` endpoint for liveness
- DB connectivity check on startup
- model-load check on startup
- centralized logs
- basic application metrics and alerts

## 8. Recommended deployment order

1. Prepare production secrets.
2. Provision DB and run migrations.
3. Deploy backend with Gunicorn.
4. Configure frontend API base URL.
5. Validate HTTPS and CORS.
6. Confirm login, dashboard, and prediction flows work.
7. Enable backups and monitoring.

## 9. Release gate

Do not publish until all of the following are true:

- `ENVIRONMENT=production`
- `DEBUG=false`
- `SECRET_KEY` is not default
- `CORS_ORIGINS` is restricted
- database is production-backed and backed up
- backend is served by a production WSGI/ASGI server
- health checks and monitoring are live
- password reset flow is real and secure
