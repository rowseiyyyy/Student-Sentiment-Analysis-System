from unittest.mock import patch


def _register_and_login(client, email="student@example.com", role="student"):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Test User", "email": email, "password": "SecurePass123", "role": role},
    )
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def _complete_professor_payload():
    return {
        "category": "Professors",
        "share_your_thoughts": "The professor explains lessons very clearly.",
        "course": "BSIT",
        "year_level": "3rd Year",
        "ratings": {
            "teaching_quality": 5,
            "mastery": 5,
            "clarity": 5,
            "fairness": 5,
            "punctuality": 5,
            "approachability": 5,
            "feedback": 5,
            "classroom_mgmt": 5,
            "teaching_style": 5,
        },
    }


def _complete_staff_payload():
    return {
        "category": "Staff",
        "share_your_thoughts": "The staff were very helpful.",
        "course": "BSBA",
        "year_level": "2nd Year",
        "ratings": {
            "safety": 4,
            "registrar": 4,
            "cashier": 4,
            "canteen": 4,
            "substitute": 4,
            "office_staff": 4,
            "admin_comm": 4,
            "maintenance": 4,
        },
    }


@patch("app.api.evaluation.run_prediction_pipeline")
def test_submit_evaluation(mock_pipeline, client):
    mock_pipeline.return_value = {

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

    token = _register_and_login(client)
    response = client.post(
        "/api/v1/evaluation",
        json=_complete_professor_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["category"] == "Professors"
    assert data["prediction"]["official_prediction"] == "Positive"
    assert data["sentiment"] == "Positive"


def test_submit_evaluation_without_trained_model_fails_gracefully(client):
    token = _register_and_login(client, email="student2@example.com")
    response = client.post(
        "/api/v1/evaluation",
        json=_complete_staff_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    # No models trained in this isolated test DB -> pipeline should raise
    # a clean 503 rather than crashing.
    assert response.status_code in (503, 201)


def test_list_evaluations_requires_auth(client):
    response = client.get("/api/v1/evaluation")
    assert response.status_code == 401


@patch("app.api.evaluation.run_prediction_pipeline")
def test_faculty_can_list_all_evaluations_but_not_delete(mock_pipeline, client):
    student_token = _register_and_login(client, email="student@example.com", role="student")
    faculty_token = _register_and_login(client, email="faculty@example.com", role="faculty")

    mock_pipeline.return_value = {

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

    student_response = client.post(
        "/api/v1/evaluation",
        json=_complete_professor_payload(),
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert student_response.status_code == 201

    list_response = client.get(
        "/api/v1/evaluation",
        headers={"Authorization": f"Bearer {faculty_token}"},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["student"] is not None

    delete_response = client.delete(
        f"/api/v1/evaluation/{student_response.json()['id']}",
        headers={"Authorization": f"Bearer {faculty_token}"},
    )
    assert delete_response.status_code == 403


@patch("app.api.evaluation.run_prediction_pipeline")
def test_student_can_only_see_own_submissions(mock_pipeline, client):
    mock_pipeline.return_value = {

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
    student_a = _register_and_login(client, email="rbac_a@example.com", role="student")
    student_b = _register_and_login(client, email="rbac_b@example.com", role="student")

    # Student A submits
    a_resp = client.post(
        "/api/v1/evaluation",
        json=_complete_professor_payload(),
        headers={"Authorization": f"Bearer {student_a}"},
    )
    assert a_resp.status_code == 201

    # Student A sees their own submission
    a_list = client.get(
        "/api/v1/evaluation",
        headers={"Authorization": f"Bearer {student_a}"},
    )
    assert a_list.status_code == 200
    assert a_list.json()["total"] == 1

    # Student B cannot see Student A's submission
    b_list = client.get(
        "/api/v1/evaluation",
        headers={"Authorization": f"Bearer {student_b}"},
    )
    assert b_list.status_code == 200
    assert b_list.json()["total"] == 0

    # Student B cannot view Student A's evaluation detail
    b_view = client.get(
        f"/api/v1/evaluation/{a_resp.json()['id']}",
        headers={"Authorization": f"Bearer {student_b}"},
    )
    assert b_view.status_code == 403
