def _register_admin_and_login(client, email="admin@asiatech.edu.ph"):
    # Public registration was removed; users are created directly in the DB.
    client.make_user(email, role="administrator", full_name="Admin User")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def _register_student_and_login(client, email="student@asiatech.edu.ph"):
    client.make_user(email, role="student", full_name="Student User")
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
    token = _register_student_and_login(client, email="student2@asiatech.edu.ph")
    response = client.get("/api/v1/ml/performance", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_get_model_performance_empty(client):
    token = _register_admin_and_login(client, email="perfadmin@asiatech.edu.ph")
    response = client.get("/api/v1/ml/performance", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["rows"] == []
    assert data["best_model"] is None


def test_rollback_nonexistent_run_returns_404(client):
    token = _register_admin_and_login(client, email="rollbackadmin@asiatech.edu.ph")
    response = client.post(
        "/api/v1/ml/rollback",
        params={"training_history_id": "does-not-exist"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_confusion_matrix_requires_trained_model(client, db_session):
    """No TrainingHistory row exists yet for this algorithm, so the
    confusion-matrix endpoint should report 404. (The endpoint only
    queries TrainingHistory -- it never checks a service's is_ready() --
    so no model needs to be mocked as loaded for this test.)"""
    token = _register_admin_and_login(client, email="cmadmin@asiatech.edu.ph")
    response = client.get(
        "/api/v1/ml/confusion-matrix",
        params={"algorithm": "SVM"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_imported_colab_metrics_appear_in_performance_but_minilm_is_production(client, tmp_path, monkeypatch):
    """Importing the Colab metrics JSON records SVM, Naive Bayes, Logistic
    Regression and Multilingual MiniLM as research results. They must appear
    in /ml/performance, but the production model must remain Multilingual
    MiniLM — the only live sentiment model."""
    token = _register_admin_and_login(client, email="importperf@asiatech.edu.ph")

    # Keep comparison/deployment artifacts out of the real app/ml directory —
    # redirect them to a temp dir so the test cannot pollute tracked files.
    from app.core.config import settings
    monkeypatch.setattr(settings, "MODEL_METADATA_PATH", tmp_path / "model_metadata.json")
    monkeypatch.setattr(settings, "COMPARISON_RESULTS_PATH", tmp_path / "comparison_results.json")

    metrics_payload = {
        "rows": {
            "SVM": {
                "accuracy": 0.90, "precision": 0.90, "recall": 0.90,
                "f1_score": 0.90, "macro_f1": 0.89, "weighted_f1": 0.90,
            },
            "Naive Bayes": {
                "accuracy": 0.92, "precision": 0.92, "recall": 0.92,
                "f1_score": 0.92, "macro_f1": 0.91, "weighted_f1": 0.92,
            },
            "Logistic Regression": {
                "accuracy": 0.91, "precision": 0.91, "recall": 0.91,
                "f1_score": 0.91, "macro_f1": 0.90, "weighted_f1": 0.91,
            },
            "Multilingual MiniLM": {
                "accuracy": 0.95, "precision": 0.95, "recall": 0.95,
                "f1_score": 0.95, "macro_f1": 0.94, "weighted_f1": 0.95,
            },
        },
        "best_model": "Multilingual MiniLM",
    }

    import_response = client.post(
        "/api/v1/ml/import-results",
        files={"metrics_json": ("dashboard_export.json", json.dumps(metrics_payload).encode("utf-8"), "application/json")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert import_response.status_code == 200
    outcome = import_response.json()
    assert set(outcome["imported_algorithms"]) == {
        "SVM", "Naive Bayes", "Logistic Regression", "Multilingual MiniLM"
    }
    # Production is pinned to the live model, never the best-imported one.
    assert outcome["production_model"] == "Multilingual MiniLM"
    assert outcome["recommended_model"] == "Multilingual MiniLM"

    performance = client.get(
        "/api/v1/ml/performance", headers={"Authorization": f"Bearer {token}"}
    )
    assert performance.status_code == 200
    perf_data = performance.json()
    algorithms = {row["algorithm"] for row in perf_data["rows"]}
    assert {"SVM", "Naive Bayes", "Logistic Regression", "Multilingual MiniLM"} <= algorithms
    assert perf_data["best_model"] == "Multilingual MiniLM"
    production_rows = [row for row in perf_data["rows"] if row["is_production_model"]]
    assert len(production_rows) == 1
    assert production_rows[0]["algorithm"] == "Multilingual MiniLM"


def test_svm_train_save_load_predict_is_leakage_safe(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.classical_service import svm_service
    from app.services.ensembles import CLASS_ORDER

    monkeypatch.setattr(settings, "SVM_MODEL_PATH", tmp_path / "svm.pkl")
    monkeypatch.setattr(settings, "SVM_VECTORIZER_PATH", tmp_path / "svm_tfidf.pkl")
    texts, labels = [], []
    for label, token in zip(CLASS_ORDER, ("awful", "ordinary", "excellent")):
        for index in range(12):
            texts.append(f"{token} classroom experience {index}")
            labels.append(label)
    split = int(len(texts) * 0.7)
    metrics = svm_service.train_on_split(
        texts[:split], labels[:split],
        test_texts=texts[split:], test_labels=labels[split:],
    )
    assert metrics["labels"] == list(CLASS_ORDER)
    assert len(metrics["confusion_matrix"]) == 3
    assert (tmp_path / "svm.pkl").exists()
    label, confidence, probabilities = svm_service.predict("excellent classroom experience")
    assert label in CLASS_ORDER
    assert 0 <= confidence <= 1
    assert len(probabilities) == 3
    assert abs(sum(probabilities) - 1) < 1e-6


def test_classical_tfidf_excludes_test_only_vocabulary(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.classical_service import naive_bayes_service

    monkeypatch.setattr(settings, "NAIVE_BAYES_MODEL_PATH", tmp_path / "nb.pkl")
    monkeypatch.setattr(settings, "NAIVE_BAYES_VECTORIZER_PATH", tmp_path / "nb_tfidf.pkl")
    train_texts = ["bad train", "neutral train", "good train"] * 3
    train_labels = ["Negative", "Neutral", "Positive"] * 3
    test_texts = ["bad testonlytoken", "neutral testonlytoken", "good testonlytoken"]
    test_labels = ["Negative", "Neutral", "Positive"]
    naive_bayes_service.train_on_split(
        train_texts, train_labels,
        test_texts=test_texts, test_labels=test_labels,
    )
    # Leakage-safe: the TF-IDF vectorizer is fitted on the train split only,
    # so test-only vocabulary never enters the feature space.
    assert "testonlytoken" not in naive_bayes_service.vectorizer.vocabulary_


def test_logistic_regression_predict_probabilities_sum_to_one(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.classical_service import logistic_regression_service
    from app.services.ensembles import CLASS_ORDER

    monkeypatch.setattr(settings, "LOGREG_MODEL_PATH", tmp_path / "logreg.pkl")
    monkeypatch.setattr(settings, "LOGREG_VECTORIZER_PATH", tmp_path / "logreg_tfidf.pkl")
    texts, labels = [], []
    for label, token in zip(CLASS_ORDER, ("awful", "ordinary", "excellent")):
        for index in range(12):
            texts.append(f"{token} classroom experience {index}")
            labels.append(label)
    split = int(len(texts) * 0.7)
    logistic_regression_service.train_on_split(
        texts[:split], labels[:split],
        test_texts=texts[split:], test_labels=labels[split:],
    )
    label, confidence, probabilities = logistic_regression_service.predict("excellent classroom experience")
    assert label in CLASS_ORDER
    assert 0 <= confidence <= 1
    assert abs(sum(probabilities) - 1) < 1e-6
import json

from app.models.prediction import AlgorithmName
from app.models.training_history import TrainingAlgorithm


def test_approved_active_models_are_registered():
    active = {item.value for item in TrainingAlgorithm}
    assert {"SVM", "Naive Bayes", "Logistic Regression", "Multilingual MiniLM"}.issubset(active)
    assert {"SVM", "Naive Bayes", "Logistic Regression", "Multilingual MiniLM"}.issubset({item.value for item in AlgorithmName})