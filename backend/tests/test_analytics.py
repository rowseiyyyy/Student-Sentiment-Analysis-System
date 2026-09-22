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


# ============================================================
# Course analytics (Sentiment by Courses chart)
# ============================================================

def _seed_course_evaluation(
    db_session, *, evaluation_id, sentiment, course, category="Professors", created_at=None
):
    """Insert one evaluation carrying a course + its prediction.

    ``course`` is passed through as-is (including None) so tests can prove the
    endpoint's behaviour for submissions that never named a program.
    """
    from app.core.time import utcnow_naive
    from app.models.evaluation import Evaluation, EvaluationCategory
    from app.models.prediction import AlgorithmName, Prediction, SentimentLabel

    stamp = created_at or utcnow_naive()
    db_session.add(
        Evaluation(
            id=evaluation_id,
            category=EvaluationCategory(category),
            comment=f"Comment for {evaluation_id}",
            course=course,
            created_at=stamp,
        )
    )
    db_session.add(
        Prediction(
            evaluation_id=evaluation_id,
            official_prediction=SentimentLabel(sentiment),
            algorithm_used=AlgorithmName.MINILM,
            confidence_score=0.9,
            processing_time_ms=12.0,
            created_at=stamp,
        )
    )
    db_session.commit()


def test_course_analytics_empty_db(client):
    token = _register_admin_and_login(client, email="courses_empty_admin@asiatech.edu.ph")
    response = client.get("/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    # Nothing to rank yet: an empty list, not a fabricated "Unknown" bucket.
    assert response.json()["points"] == []


def test_course_analytics_requires_auth(client):
    assert client.get("/api/v1/analytics/courses").status_code == 401


def test_course_analytics_scores_and_sorts_descending(client, db_session):
    """Net score is (positive - negative) / total * 100, best course first."""
    token = _register_admin_and_login(client, email="courses_scores_admin@asiatech.edu.ph")
    # BSA: one positive only -> +100.
    _seed_course_evaluation(db_session, evaluation_id="c-bsa", sentiment="Positive", course="BSA")
    # BSIT/AIT: three positive + one negative -> (3 - 1) / 4 * 100 = +50.
    for index, sentiment in enumerate(["Positive", "Positive", "Positive", "Negative"]):
        _seed_course_evaluation(
            db_session, evaluation_id=f"c-bsit-{index}", sentiment=sentiment, course="BSIT/AIT"
        )
    # BSCS: one positive + one negative -> 0 (they cancel out).
    _seed_course_evaluation(db_session, evaluation_id="c-bscs-p", sentiment="Positive", course="BSCS")
    _seed_course_evaluation(db_session, evaluation_id="c-bscs-n", sentiment="Negative", course="BSCS")
    # BSCRIM: negative only -> -100, so a course can score below zero.
    _seed_course_evaluation(db_session, evaluation_id="c-bscrim", sentiment="Negative", course="BSCRIM")

    response = client.get("/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    points = response.json()["points"]

    # The chart plots this order top-to-bottom, so it must already be
    # descending: the course with the best score comes first.
    assert [p["course"] for p in points] == ["BSA", "BSIT/AIT", "BSCS", "BSCRIM"]
    assert [p["sentiment_score"] for p in points] == [100.0, 50.0, 0.0, -100.0]
    scores = [p["sentiment_score"] for p in points]
    assert scores == sorted(scores, reverse=True)

    by_course = {p["course"]: p for p in points}
    assert by_course["BSIT/AIT"]["positive"] == 3
    assert by_course["BSIT/AIT"]["negative"] == 1
    assert by_course["BSIT/AIT"]["total"] == 4
    assert by_course["BSCS"]["neutral"] == 0


def test_course_analytics_skips_submissions_without_a_course(client, db_session):
    """A submission that named no program cannot be attributed to one."""
    token = _register_admin_and_login(client, email="courses_blank_admin@asiatech.edu.ph")
    _seed_course_evaluation(
        db_session, evaluation_id="c-named", sentiment="Positive", course="BSIT/AIT"
    )
    # Legacy/anonymous rows: course never captured (NULL), or stored blank.
    _seed_course_evaluation(db_session, evaluation_id="c-null", sentiment="Negative", course=None)
    _seed_course_evaluation(db_session, evaluation_id="c-blank", sentiment="Negative", course="   ")

    response = client.get("/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    points = response.json()["points"]
    # Only the named course is ranked -- no "Unknown" bar is invented, and the
    # unanswered rows cannot drag its score down either.
    assert [p["course"] for p in points] == ["BSIT/AIT"]
    assert points[0]["sentiment_score"] == 100.0
    assert points[0]["negative"] == 0


def test_course_analytics_damps_score_with_neutral_submissions(client, db_session):
    """Neutral submissions sit in the denominator, so they pull scores to 0."""
    token = _register_admin_and_login(client, email="courses_neutral_admin@asiatech.edu.ph")
    # One positive submission alone -> +100.
    _seed_course_evaluation(db_session, evaluation_id="c-one-pos", sentiment="Positive", course="BSA")
    # One positive among nine neutrals -> (1 - 0) / 10 * 100 = +10, not +100.
    _seed_course_evaluation(
        db_session, evaluation_id="c-mixed-pos", sentiment="Positive", course="BSCS"
    )
    for index in range(9):
        _seed_course_evaluation(
            db_session, evaluation_id=f"c-mixed-neutral-{index}", sentiment="Neutral", course="BSCS"
        )

    response = client.get("/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert {p["course"]: p["sentiment_score"] for p in response.json()["points"]} == {
        "BSA": 100.0,
        "BSCS": 10.0,
    }


def test_course_analytics_tie_break_prefers_more_submissions(client, db_session):
    """Equal scores fall back to volume, so the better-evidenced course leads."""
    token = _register_admin_and_login(client, email="courses_tie_admin@asiatech.edu.ph")
    # Both score +100: "BSIT/AIT" off two submissions, "BSA" off one. Alphabetical
    # order would put BSA first, so this proves the volume tie-break is applied.
    for index in range(2):
        _seed_course_evaluation(
            db_session, evaluation_id=f"c-tie-bsit-{index}", sentiment="Positive", course="BSIT/AIT"
        )
    _seed_course_evaluation(db_session, evaluation_id="c-tie-bsa", sentiment="Positive", course="BSA")

    response = client.get("/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    points = response.json()["points"]
    assert [p["course"] for p in points] == ["BSIT/AIT", "BSA"]
    assert [p["total"] for p in points] == [2, 1]


def test_course_analytics_category_filter(client, db_session):
    token = _register_admin_and_login(client, email="courses_category_admin@asiatech.edu.ph")
    _seed_course_evaluation(
        db_session, evaluation_id="c-cat-prof", sentiment="Positive", course="BSIT/AIT",
        category="Professors",
    )
    _seed_course_evaluation(
        db_session, evaluation_id="c-cat-staff", sentiment="Negative", course="BSIT/AIT",
        category="Staff",
    )

    # "Faculty" is a legacy alias normalized onto "Professors".
    response = client.get(
        "/api/v1/analytics/courses",
        params={"category": "Faculty"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    points = response.json()["points"]
    assert [p["course"] for p in points] == ["BSIT/AIT"]
    assert points[0]["positive"] == 1
    assert points[0]["negative"] == 0


def test_course_analytics_rejects_out_of_range_days(client):
    token = _register_admin_and_login(client, email="courses_days_admin@asiatech.edu.ph")
    response = client.get(
        "/api/v1/analytics/courses",
        params={"days": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
