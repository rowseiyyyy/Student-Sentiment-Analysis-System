import pytest

from app.core.config import Settings, assert_production_readiness, settings


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


def test_readiness_endpoint_reports_database_and_model_state(client):
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "connected"
    assert payload["models"] == "ready"
