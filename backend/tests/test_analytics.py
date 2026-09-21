from datetime import datetime


def _register_admin_and_login(client, email="admin_analytics@asiatech.edu.ph"):
    # Public registration was removed; users are created directly in the DB.
    client.make_user(email, role="administrator", full_name="Admin Analytics")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def test_overall_analytics_empty_db(client):
    token = _register_admin_and_login(client)
    response = client.get("/api/v1/analytics/overall", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["breakdown"]["total"] == 0
    assert data["evaluation_volume"] == 0


def test_category_analytics_requires_valid_category(client):
    token = _register_admin_and_login(client, email="admin_analytics2@asiatech.edu.ph")
    response = client.get(
        "/api/v1/analytics/category",
        params={"category": "Faculty"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    # Legacy "Faculty" is normalized onto the canonical enum value.
    assert response.json()["category"] == "Professors"


def test_analytics_requires_auth(client):
    response = client.get("/api/v1/analytics/overall")
    assert response.status_code == 401


def test_csv_export_requires_auth(client):
    response = client.get("/api/v1/analytics/export/csv")
    assert response.status_code == 401


def test_monthly_trend_empty_db(client):
    token = _register_admin_and_login(client, email="monthly_admin@asiatech.edu.ph")
    response = client.get("/api/v1/analytics/monthly", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "points" in data


def test_daily_trend_empty_db(client):
    token = _register_admin_and_login(client, email="daily_admin@asiatech.edu.ph")
    response = client.get("/api/v1/analytics/daily", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "points" in data


def test_word_frequency_requires_valid_sentiment(client):
    token = _register_admin_and_login(client, email="wf_admin@asiatech.edu.ph")
    response = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Positive", "top_n": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "words" in response.json()


def test_top_complaints_and_appreciations_empty(client):
    token = _register_admin_and_login(client, email="tc_admin@asiatech.edu.ph")
    complaints = client.get(
        "/api/v1/analytics/top-complaints",
        params={"limit": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert complaints.status_code == 200
    appreciations = client.get(
        "/api/v1/analytics/top-appreciations",
        params={"limit": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert appreciations.status_code == 200


def test_csv_export_with_data(client):
    from unittest.mock import patch

    token = _register_admin_and_login(client, email="csvdata_admin@asiatech.edu.ph")
    # The export endpoint joins Evaluation + Prediction. With an empty DB
    # it should still return a valid CSV with only the header row.
    response = client.get(
        "/api/v1/analytics/export/csv",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    body = response.text
    assert "evaluation_id" in body


# ============================================================
# Academic-term analytics (Sentiment by Academic Term chart)
# ============================================================

def _seed_evaluation(db_session, *, evaluation_id, category, sentiment, created_at):
    """Insert one evaluation + its prediction so analytics joins can see it."""
    from app.models.evaluation import Evaluation, EvaluationCategory
    from app.models.prediction import AlgorithmName, Prediction, SentimentLabel

    db_session.add(
        Evaluation(
            id=evaluation_id,
            category=EvaluationCategory(category),
            comment=f"Comment for {evaluation_id}",
            created_at=created_at,
        )
    )
    db_session.add(
        Prediction(
            evaluation_id=evaluation_id,
            official_prediction=SentimentLabel(sentiment),
            algorithm_used=AlgorithmName.MINILM,
            confidence_score=0.9,
            processing_time_ms=12.0,
            created_at=created_at,
        )
    )
    db_session.commit()


# The real grading calendar is eight single-month periods -- four per
# semester -- in this order (see settings.ACADEMIC_TERM_MONTHS):
#   Term 1 (1st sem): Prelim = Jul, Midterm = Aug, Prefinal = Sep, Finals = Oct
#   Term 2 (2nd sem): Prelim = Feb, Midterm = Mar, Prefinal = Apr, Finals = May
# Nov, Dec, Jan and Jun are breaks/enrollment and belong to no period.
_TERM_ORDER = [
    "Term 1 Prelim", "Term 1 Midterm", "Term 1 Prefinal", "Term 1 Finals",
    "Term 2 Prelim", "Term 2 Midterm", "Term 2 Prefinal", "Term 2 Finals",
]


def test_term_analytics_empty_db(client):
    token = _register_admin_and_login(client, email="terms_admin@asiatech.edu.ph")
    response = client.get("/api/v1/analytics/terms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    # All eight configured grading periods are returned, zero-filled, in
    # calendar order so the chart keeps a stable x-axis (Term 1 first, then
    # Term 2) even with no submissions yet. The chart shows these eight
    # periods, not the twelve calendar months.
    assert [p["term"] for p in data["points"]] == _TERM_ORDER
    assert all(p["total"] == 0 for p in data["points"])


def test_term_analytics_requires_auth(client):
    assert client.get("/api/v1/analytics/terms").status_code == 401


def test_term_analytics_buckets_by_submission_month(client, db_session):
    """Prior-month submissions re-bucket correctly under the new calendar."""
    token = _register_admin_and_login(client, email="termbucket_admin@asiatech.edu.ph")
    # New calendar is single-month periods: Term 1 Prelim = Jul, Term 1
    # Midterm = Aug, Term 2 Midterm = Mar, Term 2 Finals = May.
    _seed_evaluation(
        db_session, evaluation_id="term-t1-prelim", category="Professors",
        sentiment="Positive", created_at=datetime(2026, 7, 15, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="term-t1-midterm", category="Professors",
        sentiment="Negative", created_at=datetime(2026, 8, 15, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="term-t2-finals", category="Staff",
        sentiment="Neutral", created_at=datetime(2026, 5, 15, 9, 0, 0),
    )

    response = client.get("/api/v1/analytics/terms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert [p["term"] for p in data["points"]] == _TERM_ORDER
    points = {p["term"]: p for p in data["points"]}

    assert points["Term 1 Prelim"]["positive"] == 1
    assert points["Term 1 Prelim"]["total"] == 1
    assert points["Term 1 Midterm"]["negative"] == 1
    assert points["Term 2 Finals"]["neutral"] == 1
    # A period with no submissions is still present, zero-filled.
    assert points["Term 2 Prefinal"]["total"] == 0


def test_term_analytics_excludes_break_months(client, db_session):
    """Nov/Dec/Jan/Jun belong to no period: skipped, never guessed or errored."""
    token = _register_admin_and_login(client, email="termbreak_admin@asiatech.edu.ph")
    for month in (1, 6, 11, 12):
        _seed_evaluation(
            db_session, evaluation_id=f"term-break-{month}", category="Professors",
            sentiment="Positive", created_at=datetime(2026, month, 10, 9, 0, 0),
        )
    # One in-calendar submission proves the endpoint still aggregates normally
    # alongside the excluded rows.
    _seed_evaluation(
        db_session, evaluation_id="term-in-calendar", category="Professors",
        sentiment="Negative", created_at=datetime(2026, 7, 10, 9, 0, 0),
    )

    response = client.get("/api/v1/analytics/terms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    # The x-axis still lists exactly the eight defined periods, in calendar
    # order -- the four break months contribute no extra buckets.
    assert [p["term"] for p in data["points"]] == _TERM_ORDER
    # Only the in-calendar submission is counted; the break-month rows were
    # dropped rather than folded into the nearest grading period.
    assert sum(p["total"] for p in data["points"]) == 1
    points = {p["term"]: p for p in data["points"]}
    assert points["Term 1 Prelim"]["negative"] == 1
    assert all(p["positive"] == 0 for p in data["points"])


def test_term_analytics_rebuckets_every_month_under_new_calendar(client, db_session):
    """One submission per calendar month proves the full 12 -> 8 remapping.

    Existing submissions from prior months must land in the new single-month
    periods (Jul-Oct, Feb-May) and the four break months must drop out, while
    the zero-filled x-axis still shows all eight periods in calendar order.
    """
    token = _register_admin_and_login(client, email="termmatrix_admin@asiatech.edu.ph")
    for month in range(1, 13):
        _seed_evaluation(
            db_session, evaluation_id=f"term-matrix-{month}", category="Professors",
            sentiment="Positive", created_at=datetime(2026, month, 5, 9, 0, 0),
        )

    response = client.get("/api/v1/analytics/terms", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    points = response.json()["points"]

    # Eight defined periods in calendar order -- never all twelve months.
    assert [p["term"] for p in points] == _TERM_ORDER
    # Exactly one submission lands in each in-calendar period; the Jan/Jun/
    # Nov/Dec submissions (4 of the 12) are excluded from every bucket.
    assert [p["total"] for p in points] == [1] * 8
    assert sum(p["total"] for p in points) == 8


def test_term_analytics_category_filter(client, db_session):
    token = _register_admin_and_login(client, email="termcategory_admin@asiatech.edu.ph")
    _seed_evaluation(
        db_session, evaluation_id="term-professor", category="Professors",
        sentiment="Positive", created_at=datetime(2026, 7, 15, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="term-staff", category="Staff",
        sentiment="Negative", created_at=datetime(2026, 7, 16, 9, 0, 0),
    )

    # "Faculty" is a legacy alias normalized onto "Professors".
    response = client.get(
        "/api/v1/analytics/terms",
        params={"category": "Faculty"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    points = {p["term"]: p for p in response.json()["points"]}
    assert points["Term 1 Prelim"]["positive"] == 1
    assert points["Term 1 Prelim"]["negative"] == 0
    assert points["Term 1 Prelim"]["total"] == 1


def test_term_analytics_rejects_out_of_range_days(client):
    token = _register_admin_and_login(client, email="termdays_admin@asiatech.edu.ph")
    response = client.get(
        "/api/v1/analytics/terms",
        params={"days": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
