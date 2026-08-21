def _register_admin_and_login(client, email="admin@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Admin User",
            "email": email,
            "password": "SecurePass123",
            "role": "administrator",
        },
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def _register_student_and_login(client, email="student@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Student User", "email": email, "password": "SecurePass123", "role": "student"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def test_non_admin_cannot_upload_dataset(client, tmp_path):
    token = _register_student_and_login(client)
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text("id,category,comment,sentiment\n1,Faculty,Great teacher,Positive\n")

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/ml/dataset/upload",
            files={"file": ("feedback.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


def test_admin_can_upload_valid_dataset(client, tmp_path):
    token = _register_admin_and_login(client)

    rows = ["id,category,comment,sentiment"]
    sentiments = ["Positive", "Neutral", "Negative"]
    categories = ["Faculty", "Staff", "Payment", "Facilities"]
    for i in range(40):
        rows.append(f"{i},{categories[i % 4]},Sample comment number {i},{sentiments[i % 3]}")
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text("\n".join(rows))

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/ml/dataset/upload",
            files={"file": ("feedback.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["rows"] == 40


def test_upload_rejects_non_csv(client, tmp_path):
    token = _register_admin_and_login(client)
    txt_path = tmp_path / "feedback.txt"
    txt_path.write_text("not a csv")

    with open(txt_path, "rb") as f:
        response = client.post(
            "/api/v1/ml/dataset/upload",
            files={"file": ("feedback.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 400


def test_get_model_performance_requires_admin(client):
    token = _register_student_and_login(client, email="student2@example.com")
    response = client.get("/api/v1/ml/performance", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_get_model_performance_empty(client):
    token = _register_admin_and_login(client, email="perfadmin@example.com")
    response = client.get("/api/v1/ml/performance", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["rows"] == []
    assert data["best_model"] is None


def test_rollback_nonexistent_run_returns_404(client):
    token = _register_admin_and_login(client, email="rollbackadmin@example.com")
    response = client.post(
        "/api/v1/ml/rollback",
        params={"training_history_id": "does-not-exist"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_confusion_matrix_requires_trained_model(client, db_session):
    from unittest.mock import patch

    token = _register_admin_and_login(client, email="cmadmin@example.com")
    with patch("app.services.svm_service.svm_service.is_ready", return_value=True):
        response = client.get(
            "/api/v1/ml/confusion-matrix",
            params={"algorithm": "SVM"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 404


def test_xgboost_train_save_load_predict_is_leakage_safe(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "XGB_MODEL_PATH", tmp_path / "xgb.pkl")
    monkeypatch.setattr(settings, "XGB_TFIDF_VECTORIZER_PATH", tmp_path / "tfidf.pkl")
    monkeypatch.setattr(settings, "XGB_LABEL_ENCODER_PATH", tmp_path / "labels.json")
    texts, labels = [], []
    for label, token in zip(CLASS_ORDER, ("awful", "ordinary", "excellent")):
        for index in range(12):
            texts.append(f"{token} classroom experience {index}")
            labels.append(label)
    service = XGBoostService()
    metrics = service.train(texts, labels)
    assert metrics["labels"] == list(CLASS_ORDER)
    assert len(metrics["confusion_matrix"]) == 3
    assert (tmp_path / "xgb.pkl").exists()
    loaded = XGBoostService()
    label, confidence, probabilities = loaded.predict("excellent classroom experience")
    assert label in CLASS_ORDER
    assert 0 <= confidence <= 1
    assert len(probabilities) == 3
    assert abs(sum(probabilities) - 1) < 1e-6
    assert "classes" in json.loads((tmp_path / "labels.json").read_text())


def test_xgboost_tfidf_excludes_test_only_vocabulary(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "XGB_MODEL_PATH", tmp_path / "xgb.pkl")
    monkeypatch.setattr(settings, "XGB_TFIDF_VECTORIZER_PATH", tmp_path / "tfidf.pkl")
    monkeypatch.setattr(settings, "XGB_LABEL_ENCODER_PATH", tmp_path / "labels.json")
    train_texts = ["bad train", "neutral train", "good train"] * 3
    train_labels = ["Negative", "Neutral", "Positive"] * 3
    val_texts = ["bad validation", "neutral validation", "good validation"]
    val_labels = ["Negative", "Neutral", "Positive"]
    test_texts = ["bad testonlytoken", "neutral testonlytoken", "good testonlytoken"]
    test_labels = ["Negative", "Neutral", "Positive"]
    splits = iter([(train_texts + val_texts, test_texts, train_labels + val_labels, test_labels), (train_texts, val_texts, train_labels, val_labels)])
    monkeypatch.setattr("app.services.xgboost_service.train_test_split", lambda *args, **kwargs: next(splits))
    service = XGBoostService()
    service.train(train_texts + val_texts + test_texts, train_labels + val_labels + test_labels)
    assert "testonlytoken" not in service.vectorizer.vocabulary_
import json

from app.models.prediction import AlgorithmName
from app.models.training_history import TrainingAlgorithm
from app.services.xgboost_service import CLASS_ORDER, XGBoostService
from app.services.transformer_service import TransformerSentimentService


def test_transformer_probability_mapping_uses_application_order():
    probabilities = TransformerSentimentService.align_probabilities(
        [0.7, 0.2, 0.1], {0: "POSITIVE", 1: "NEGATIVE", 2: "NEUTRAL"}
    )
    assert probabilities == [0.2, 0.1, 0.7]
    assert abs(sum(probabilities) - 1) < 1e-9


def test_approved_active_models_are_registered():
    active = {item.value for item in TrainingAlgorithm}
    assert {"XGBoost", "DeBERTa", "RoBERTa", "Ensemble"}.issubset(active)
    assert {"XGBoost", "DeBERTa", "RoBERTa", "Ensemble (soft vote)"}.issubset({item.value for item in AlgorithmName})
