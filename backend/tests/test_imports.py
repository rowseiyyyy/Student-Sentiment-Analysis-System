from unittest.mock import patch

PREDICTION_RESULT = {
    "xgb_prediction": "Positive",
    "xgb_confidence": 0.91,
    "deberta_prediction": "Positive",
    "deberta_confidence": 0.90,
    "roberta_prediction": "Positive",
    "roberta_confidence": 0.90,
    "official_prediction": "Positive",
    "algorithm_used": "XGBoost",
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
        "Respondent_ID,Course,Share your thoughts\n"
        "2019-0001,BS IT,The professor explains well.\n"
        "2019-0002,BS IT,The professor is very approachable.\n"
    )

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.csv", f, "text/csv")},
            data={"category": "Faculty"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["imported"] == 2
    assert data["failed"] == 0


COMBINED_CSV = (
    "Respondent_ID,Course,"
    "Staff_Safety,Staff_Comments,"
    "Professor_TeachingQuality,Professor_Comments,"
    "Facilities_Cleanliness,Facilities_Comments,"
    "Payments_Queues,Payments_Comments\n"
    "2019-0001,BS IT,5,Staff were friendly.,4,Very clear teaching.,3,Clean rooms.,2,Long queues.\n"
)


@patch("app.api.imports.process_imported_evaluations")
def test_import_combined_csv_auto_detected(mock_process, client, tmp_path):
    """A combined multi-category file expands one row to four evaluations
    without needing the ``category`` form field."""
    captured = {}

    def fake_process(db, clean_rows, run_prediction=True, **kwargs):
        captured["clean_rows"] = clean_rows
        return type("R", (), {"total_rows": len(clean_rows), "imported": len(clean_rows), "failed": 0, "errors": []})()

    mock_process.side_effect = fake_process
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "combined.csv"
    csv_path.write_text(COMBINED_CSV)

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("combined.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["imported"] == 4
    assert data["failed"] == 0

    rows = captured["clean_rows"]
    assert sorted(r["category"] for r in rows) == [
        "Facilities", "Faculty", "Payment", "Staff",
    ]
    for r in rows:
        assert r["student_id"] == "2019-0001"
        assert r["course"] == "BS IT"
        assert r["share_your_thoughts"]
        assert r["ratings"]
    faculty = next(r for r in rows if r["category"] == "Faculty")
    assert faculty["ratings"] == {"teaching_quality": 4}



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
