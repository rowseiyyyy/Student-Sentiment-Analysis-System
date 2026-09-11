import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings, assert_production_readiness, settings


def test_missing_required_env_fields_fail_fast(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    monkeypatch.delenv("DB_PORT", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    with pytest.raises(ValidationError):
        Settings()


def test_assert_production_readiness_rejects_debug_true(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "DEBUG", True, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-very-long-production-secret-key-1234567890", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://feedback.example.com"], raising=False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://feedback.example.com", raising=False)

    with pytest.raises(RuntimeError, match="DEBUG must be False"):
        assert_production_readiness()


def test_assert_production_readiness_rejects_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_1234567890", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://feedback.example.com"], raising=False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://feedback.example.com", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY is still the default value"):
        assert_production_readiness()


def test_assert_production_readiness_rejects_permissive_cors(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-very-long-production-secret-key-1234567890", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"], raising=False)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://feedback.example.com", raising=False)

    with pytest.raises(RuntimeError, match="CORS_ORIGINS is wide-open"):
        assert_production_readiness()


def test_settings_loads_email_and_frontend_deployment_fields(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://feedback.example.com")

    cfg = Settings()
    assert cfg.SMTP_HOST == "smtp.example.com"
    assert cfg.SMTP_PORT == 587
    assert cfg.SMTP_USERNAME == "mailer@example.com"
    assert cfg.SMTP_FROM_EMAIL == "no-reply@example.com"
    assert cfg.FRONTEND_URL == "https://feedback.example.com"


def test_assert_production_readiness_rejects_localhost_cors(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    monkeypatch.setattr(settings, "DEBUG", False, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-very-long-production-secret-key-1234567890", raising=False)
    monkeypatch.setattr(
        settings,
        "CORS_ORIGINS",
        ["http://localhost:3000", "https://example.com"],
        raising=False,
    )

    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        assert_production_readiness()


def test_database_url_round_trips_special_characters_and_ssl_mode():
    cfg = Settings(
        SECRET_KEY="a-very-long-production-secret-key-1234567890",
        CORS_ORIGINS=["https://feedback.example.com"],
        FRONTEND_URL="https://feedback.example.com",
        DB_HOST="localhost",
        DB_PORT=3306,
        DB_USER="user/name@example",
        DB_PASSWORD="pa:ss@word",
        DB_NAME="app",
        DB_DRIVER="mysql+pymysql",
    )

    parsed = make_url(cfg.DATABASE_URL)
    assert parsed.drivername == "mysql+pymysql"
    assert parsed.username == "user/name@example"
    assert parsed.password == "pa:ss@word"
    assert parsed.host == "localhost"
    assert parsed.port == 3306
    assert parsed.database == "app"
    assert dict(parsed.query) == {}


def test_readiness_endpoint_reports_database_and_model_state(client):
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "connected"
    assert payload["models"] == "ready"
