from unittest.mock import patch

from app.models.training_history import TrainingHistory
from app.services.prediction import run_prediction_pipeline

PREDICTION_RESULT = {
    "svm_prediction": "Positive",
    "svm_confidence": 0.91,
    "random_forest_prediction": "Positive",
    "random_forest_confidence": 0.88,
    "naive_bayes_prediction": "Neutral",
    "naive_bayes_confidence": 0.70,
    "bert_prediction": "Positive",
    "bert_confidence": 0.95,
    "xgb_prediction": "Positive",
    "xgb_confidence": 0.91,
    "deberta_prediction": "Positive",
    "deberta_confidence": 0.90,
    "roberta_prediction": "Positive",
    "roberta_confidence": 0.90,
    "ensemble_prediction": "Positive",
    "ensemble_confidence": 0.90,
    "official_prediction": "Positive",
    "algorithm_used": "SVM",
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


def test_run_prediction_pipeline_uses_approved_research_models(db_session):
    with patch("app.services.prediction.xgboost_service.is_ready", return_value=True), \
         patch("app.services.prediction.xgboost_service.predict", return_value=("Positive", 0.81, [0.1, 0.1, 0.8])), \
         patch("app.services.prediction.deberta_service.is_ready", return_value=True), \
         patch("app.services.prediction.deberta_service.predict", return_value=("Neutral", 0.55, [0.2, 0.6, 0.2])), \
         patch("app.services.prediction.roberta_service.is_ready", return_value=True), \
         patch("app.services.prediction.roberta_service.predict", return_value=("Positive", 0.72, [0.1, 0.2, 0.7])):
        result = run_prediction_pipeline(db_session, "The professor is very helpful.")

    assert result["official_prediction"] == "Positive"
    assert result["algorithm_used"] == "XGBoost"
    assert result["xgb_prediction"] == "Positive"
    assert result["deberta_prediction"] == "Neutral"
    assert result["roberta_prediction"] == "Positive"
    assert "ensemble_prediction" in result


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
    assert data["algorithm_used"] == "SVM"
    assert data["svm"]["prediction"] == "Positive"
    assert data["random_forest"]["prediction"] == "Positive"
    assert data["naive_bayes"]["prediction"] == "Neutral"
    assert data["bert"]["prediction"] == "Positive"
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
