from unittest.mock import patch

from app.models.training_history import TrainingHistory
from app.services.prediction import run_prediction_pipeline

PREDICTION_RESULT = {
    "xgb_prediction": "Positive",
    "xgb_confidence": 0.91,
    "deberta_prediction": "Positive",
    "deberta_confidence": 0.90,
    "roberta_prediction": "Positive",
    "roberta_confidence": 0.90,
    "ensemble_prediction": "Positive",
    "ensemble_confidence": 0.90,
    "official_prediction": "Positive",
    "algorithm_used": "XGBoost",
    "confidence_score": 0.91,
    "processing_time_ms": 12.5,
}


def _register_and_login(client, email="predictuser@example.com", role="student"):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Predict User", "email": email, "password": "SecurePass123", "role": role},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def test_run_prediction_pipeline_uses_live_minilm_model(db_session):
    # Multilingual MiniLM is the ONLY live model and produces the official
    # result. XGBoost and the transformers are not run in the request path.
    with patch("app.services.prediction.minilm_service.can_run_live_inference", return_value=True), \
         patch("app.services.prediction.minilm_service.predict", return_value=("Positive", 0.88, [0.05, 0.07, 0.88])):
        result = run_prediction_pipeline(db_session, "The professor is very helpful.")

    assert result["official_prediction"] == "Positive"
    assert result["algorithm_used"] == "Multilingual MiniLM"
    assert result["minilm_prediction"] == "Positive"
    # XGBoost is no longer part of the live request path.
    assert result["xgb_prediction"] is None
    # Transformers are not part of the live request path anymore.
    assert result["deberta_prediction"] is None
    assert result["roberta_prediction"] is None
    # Single-member "ensemble" report degenerates to the live model's result.
    assert result["ensemble_prediction"] == "Positive"


def test_run_prediction_pipeline_raises_without_minilm(db_session):
    # MiniLM is the only live model: when it is unavailable — artifacts
    # missing, prediction failing, or a host too small to load the ONNX
    # session — the pipeline raises and the API surfaces a clean 503. There
    # is no silent fallback to another model.
    with patch("app.services.prediction.minilm_service.can_run_live_inference", return_value=False):
        try:
            run_prediction_pipeline(db_session, "The professor is very helpful.")
        except RuntimeError as exc:
            assert "No sentiment model" in str(exc)
        else:
            raise AssertionError("expected RuntimeError when MiniLM cannot serve")


@patch("app.api.prediction.run_prediction_pipeline")
def test_predict_sentiment(mock_pipeline, client):
    mock_pipeline.return_value = PREDICTION_RESULT
    token = _register_and_login(client)
    response = client.post(
        "/api/v1/predict",
        json={"text": "The professor is very kind and helpful."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["official_prediction"] == "Positive"
    assert data["algorithm_used"] == "XGBoost"
    assert data["xgb"]["prediction"] == "Positive"
    assert data["deberta"]["prediction"] == "Positive"
    assert data["roberta"]["prediction"] == "Positive"
    assert data["confidence_score"] == 0.91


@patch("app.api.prediction.run_prediction_pipeline")
def test_predict_requires_auth(mock_pipeline, client):
    mock_pipeline.return_value = PREDICTION_RESULT
    response = client.post("/api/v1/predict", json={"text": "hello world"})
    assert response.status_code in (401, 403)


@patch("app.api.prediction.run_prediction_pipeline")
def test_predict_empty_text_rejected(mock_pipeline, client):
    mock_pipeline.return_value = PREDICTION_RESULT
    token = _register_and_login(client, email="emptypredict@example.com")
    response = client.post(
        "/api/v1/predict",
        json={"text": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@patch("app.api.prediction.run_prediction_pipeline")
def test_predict_pipeline_failure_returns_503(mock_pipeline, client):
    mock_pipeline.side_effect = RuntimeError("No sentiment model is currently available.")
    token = _register_and_login(client, email="failpredict@example.com")
    response = client.post(
        "/api/v1/predict",
        json={"text": "some feedback comment here"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
