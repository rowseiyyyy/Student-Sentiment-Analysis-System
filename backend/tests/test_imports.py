from unittest.mock import patch

PREDICTION_RESULT = {
    "svm_prediction": "Positive",
    "svm_confidence": 0.91,
    "random_forest_prediction": "Positive",
    "random_forest_confidence": 0.88,
    "naive_bayes_prediction": "Neutral",
    "naive_bayes_confidence": 0.70,
    "bert_prediction": "Positive",
    "bert_confidence": 0.95,
    "official_prediction": "Positive",
    "algorithm_used": "SVM",
    "confidence_score": 0.91,
    "processing_time_ms": 12.5,
}


def _register_admin_and_login(client, email="importadmin@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Import Admin", "email": email, "password": "SecurePass123", "role": "administrator"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def _register_student_and_login(client, email="importstudent@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Import Student", "email": email, "password": "SecurePass123", "role": "student"},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


@patch("app.api.imports.process_imported_evaluations")
def test_import_requires_admin(mock_process, client, tmp_path):
    token = _register_student_and_login(client)
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text("category,comment\nFaculty,Great teaching\n")

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


@patch("app.api.imports.process_imported_evaluations")
def test_import_rejects_unsupported_extension(mock_process, client, tmp_path):
    token = _register_admin_and_login(client)
    txt_path = tmp_path / "feedback.txt"
    txt_path.write_text("category,comment\nFaculty,Great\n")

    with open(txt_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 400


@patch("app.api.imports.process_imported_evaluations")
def test_import_valid_csv(mock_process, client, tmp_path):
    mock_process.return_value = type(
        "R",
        (),
        {
            "total_rows": 2,
            "imported": 2,
            "failed": 0,
            "errors": [],
        },
    )()
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text(
        "category,comment\n"
        "Faculty,The professor explains well.\n"
        "Staff,The registrar is very helpful.\n"
    )

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["imported"] == 2
    assert data["failed"] == 0


@patch("app.api.imports.process_imported_evaluations")
def test_import_empty_file_rejected(mock_process, client, tmp_path):
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("category,comment\n")

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("empty.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422
