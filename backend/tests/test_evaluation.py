from datetime import timedelta
from unittest.mock import patch

from app.api.evaluation import REQUIRED_LIKERT_QUESTIONS
from app.core.config import settings
from app.core.time import utcnow_naive


def _register_and_login(client, email="student@asiatech.edu.ph", role="student"):
    # Public registration was removed; users are created directly in the DB.
    client.make_user(email, role=role, full_name="Test User")
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


def _stub_prediction_pipeline(mock_pipeline):
    """Canned pipeline result, kept in one place for the submission tests."""
    mock_pipeline.return_value = {
        "svm_prediction": "Positive",
        "svm_confidence": 0.91,
        "naive_bayes_prediction": "Positive",
        "naive_bayes_confidence": 0.90,
        "logistic_regression_prediction": "Positive",
        "logistic_regression_confidence": 0.90,
        "official_prediction": "Positive",
        "algorithm_used": "Multilingual MiniLM",
        "confidence_score": 0.91,
        "processing_time_ms": 12.5,
    }


# The five Payments questions that existed before security / info_clarity /
# digital_trust were added, and the three that were added on top of them.
PAYMENTS_RATINGS_BEFORE_NEW_QUESTIONS = {
    "accessibility": 4,
    "processing": 4,
    "queues": 4,
    "courteous": 4,
    "accounting": 4,
}
PAYMENTS_NEW_QUESTIONS = ["security", "info_clarity", "digital_trust"]


def _payments_payload(new_questions=True):
    """A complete Payments answer set (eight questions) by default.

    ``new_questions=False`` reproduces what a student on the *previous* form
    sends: it cannot contain answers to questions that did not exist yet, which
    is exactly the case the grace window in app.core.config exists for.
    """
    ratings = dict(PAYMENTS_RATINGS_BEFORE_NEW_QUESTIONS)
    if new_questions:
        ratings.update({key: 4 for key in PAYMENTS_NEW_QUESTIONS})
    return {
        "category": "Payments",
        "share_your_thoughts": "Paying tuition at the counter is straightforward.",
        "course": "BSA",
        "year_level": "1st Year",
        "ratings": ratings,
    }


@patch("app.api.evaluation.run_prediction_pipeline")
def test_submit_evaluation(mock_pipeline, client):
    mock_pipeline.return_value = {

        "svm_prediction": "Positive",
        "svm_confidence": 0.91,
        "naive_bayes_prediction": "Positive",
        "naive_bayes_confidence": 0.90,
        "logistic_regression_prediction": "Positive",
        "logistic_regression_confidence": 0.90,
        "official_prediction": "Positive",
        "algorithm_used": "Multilingual MiniLM",
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
    token = _register_and_login(client, email="student2@asiatech.edu.ph")
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
    student_token = _register_and_login(client, email="student@asiatech.edu.ph", role="student")
    faculty_token = _register_and_login(client, email="faculty@asiatech.edu.ph", role="faculty")

    mock_pipeline.return_value = {

        "svm_prediction": "Positive",
        "svm_confidence": 0.91,
        "naive_bayes_prediction": "Positive",
        "naive_bayes_confidence": 0.90,
        "logistic_regression_prediction": "Positive",
        "logistic_regression_confidence": 0.90,
        "official_prediction": "Positive",
        "algorithm_used": "Multilingual MiniLM",
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

        "svm_prediction": "Positive",
        "svm_confidence": 0.91,
        "naive_bayes_prediction": "Positive",
        "naive_bayes_confidence": 0.90,
        "logistic_regression_prediction": "Positive",
        "logistic_regression_confidence": 0.90,
        "official_prediction": "Positive",
        "algorithm_used": "Multilingual MiniLM",
        "confidence_score": 0.91,
        "processing_time_ms": 12.5,
    }
    student_a = _register_and_login(client, email="rbac_a@asiatech.edu.ph", role="student")
    student_b = _register_and_login(client, email="rbac_b@asiatech.edu.ph", role="student")

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


# ============================================================
# Payments questions added to complete the approved set
# (security / info_clarity / digital_trust)
# ============================================================

@patch("app.api.evaluation.run_prediction_pipeline")
def test_payments_accepts_all_eight_questions(mock_pipeline, client):
    """The three added questions are required, stored, and averaged in."""
    _stub_prediction_pipeline(mock_pipeline)
    token = _register_and_login(client, email="payments_full@asiatech.edu.ph")

    response = client.post(
        "/api/v1/evaluation",
        json=_payments_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert list(data["ratings"]) == [
        *PAYMENTS_RATINGS_BEFORE_NEW_QUESTIONS,
        *PAYMENTS_NEW_QUESTIONS,
    ]
    # Every answer is a 4, so the average now covers all eight questions.
    assert data["likert_average"] == 4.0


@patch("app.api.evaluation.run_prediction_pipeline")
def test_payments_previous_form_accepted_while_grace_window_open(
    mock_pipeline, monkeypatch, client
):
    """A cached form cannot answer questions it never showed; it still submits."""
    _stub_prediction_pipeline(mock_pipeline)
    # Window explicitly open, so this does not depend on the configured default
    # or on the date the suite happens to run.
    monkeypatch.setattr(settings, "NEW_QUESTION_GRACE_UNTIL", utcnow_naive() + timedelta(days=7))
    token = _register_and_login(client, email="payments_grace@asiatech.edu.ph")

    response = client.post(
        "/api/v1/evaluation",
        json=_payments_payload(new_questions=False),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    # Only the five answers the old form could collect are stored — the three
    # new ones are absent rather than invented.
    assert list(response.json()["ratings"]) == list(PAYMENTS_RATINGS_BEFORE_NEW_QUESTIONS)


def test_payments_previous_form_after_grace_asks_student_to_refresh(monkeypatch, client):
    """Once the window closes, a stale form gets an actionable message."""
    monkeypatch.setattr(settings, "NEW_QUESTION_GRACE_UNTIL", None)
    token = _register_and_login(client, email="payments_stale@asiatech.edu.ph")

    response = client.post(
        "/api/v1/evaluation",
        json=_payments_payload(new_questions=False),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    # Listing questions the student was never shown would be a dead end.
    assert "refresh" in detail
    assert "security" not in detail


def test_payments_missing_core_question_still_names_it(monkeypatch, client):
    """A genuinely skipped question keeps the specific, itemised message."""
    monkeypatch.setattr(settings, "NEW_QUESTION_GRACE_UNTIL", None)
    token = _register_and_login(client, email="payments_skipped@asiatech.edu.ph")
    payload = _payments_payload()
    del payload["ratings"]["queues"]

    response = client.post(
        "/api/v1/evaluation",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert "queues" in response.json()["detail"]


def test_likert_min_questions_matches_smallest_form():
    """The fallback floor must never exceed the smallest live form.

    LIKERT_MIN_QUESTIONS only guards the branch for a category that has no entry
    in REQUIRED_LIKERT_QUESTIONS, so if it ever rises above a real per-category
    count it would reject complete submissions. This pins both the per-category
    counts and the relationship between the two.
    """
    counts = {category: len(questions) for category, questions in REQUIRED_LIKERT_QUESTIONS.items()}
    assert counts == {
        "Professors": 9,
        "Staff": 8,
        "Facilities": 8,
        "Payments": 8,
    }
    assert settings.LIKERT_MIN_QUESTIONS <= min(counts.values())
