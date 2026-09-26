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

def _seed_evaluation(
    db_session, *, evaluation_id, category, sentiment, created_at,
    course=None, likert_average=None, ratings=None,
):
    """Insert one evaluation + its prediction so analytics joins can see it.

    ``course`` is optional: the "Sentiment by Courses" chart only counts rows
    that named a course, so pass it when that panel is under test.
    ``likert_average`` / ``ratings`` are optional for the same reason — the
    Likert panels only see submissions that were actually rated.
    """
    from app.models.evaluation import Evaluation, EvaluationCategory
    from app.models.prediction import AlgorithmName, Prediction, SentimentLabel

    db_session.add(
        Evaluation(
            id=evaluation_id,
            category=EvaluationCategory(category),
            comment=f"Comment for {evaluation_id}",
            course=course,
            likert_average=likert_average,
            ratings=ratings,
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


# ============================================================
# Faculty scoping — the Faculty dashboard is Professors-only.
#
# A faculty account reviews professor feedback only, so the three panels on
# its Analytics tab (Monthly Trend, Sentiment by Courses, Top Comments) must
# never mix in Staff / Facilities / Payments rows — not even when the request
# explicitly asks for another category. The Admin dashboard is unaffected.
# ============================================================


def _login_faculty(client, email="scoped_faculty@asiatech.edu.ph"):
    client.make_user(email, role="faculty", full_name="Scoped Faculty")
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    return login.json()["access_token"]


def _seed_mixed_categories(db_session):
    """Two Professors rows (one per sentiment) plus one row in every other
    category, all in the same month so a monthly bucket can be compared."""
    _seed_evaluation(
        db_session, evaluation_id="scope-prof-pos", category="Professors",
        sentiment="Positive", course="BSCS",
        created_at=datetime(2026, 7, 15, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="scope-prof-neg", category="Professors",
        sentiment="Negative", course="BSCS",
        created_at=datetime(2026, 7, 15, 10, 0, 0),
    )
    for category in ("Staff", "Facilities", "Payments"):
        _seed_evaluation(
            db_session, evaluation_id=f"scope-{category.lower()}", category=category,
            sentiment="Negative", course="BSIT",
            created_at=datetime(2026, 7, 16, 9, 0, 0),
        )


def test_faculty_monthly_trend_is_scoped_to_professors(client, db_session):
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/analytics/monthly", headers=headers)
    assert response.status_code == 200
    points = response.json()["points"]
    # Only the two Professors rows land in the bucket; the other three
    # categories are not summed into it.
    assert [p["total"] for p in points] == [2]
    assert points[0]["positive"] == 1
    assert points[0]["negative"] == 1


def test_faculty_cannot_widen_its_own_scope(client, db_session):
    """Hand-crafting ?category=Staff must not hand faculty that category."""
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    asked_for_staff = client.get(
        "/api/v1/analytics/monthly", params={"category": "Staff"}, headers=headers
    )
    assert asked_for_staff.status_code == 200
    # Pinned back to Professors by the server.
    assert [p["total"] for p in asked_for_staff.json()["points"]] == [2]

    comments = client.get(
        "/api/v1/analytics/top-complaints",
        params={"category": "Staff", "limit": 10},
        headers=headers,
    )
    assert comments.status_code == 200
    assert {item["category"] for item in comments.json()["items"]} == {"Professors"}


def test_faculty_daily_and_terms_are_scoped(client, db_session):
    """The daily and term charts must not mix in the other departments.

    Regression test for the scoping bypass: /analytics/daily and /terms
    forwarded the caller's category straight to the service, so a faculty
    token could read the Staff / Facilities / Payments panels that every
    other route refused them.
    """
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    daily = client.get(
        "/api/v1/analytics/daily", params={"category": "Staff"}, headers=headers
    )
    assert daily.status_code == 200
    # Only the two Professors rows; the Staff row is not summed in.
    assert [p["total"] for p in daily.json()["points"]] == [2]

    terms = client.get(
        "/api/v1/analytics/terms", params={"category": "Staff"}, headers=headers
    )
    assert terms.status_code == 200
    assert sum(p["total"] for p in terms.json()["points"]) == 2


def test_faculty_term_comparison_is_scoped(client, db_session):
    """term_comparison delegates to term_analytics, so pinning /terms closes
    this route too.

    Asserted as agreement with the term chart rather than an absolute total:
    term-comparison reports the *current* calendar period, and the fixtures are
    seeded in the past, so the current period legitimately has no rows. What
    matters is that faculty cannot widen the scope -- so its numbers must be
    identical to an admin request pinned to the same category.
    """
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    faculty = client.get(
        "/api/v1/analytics/term-comparison",
        params={"category": "Staff"},
        headers=headers,
    )
    assert faculty.status_code == 200

    admin_token = _register_admin_and_login(
        client, email="term_cmp_admin@asiatech.edu.ph"
    )
    admin = client.get(
        "/api/v1/analytics/term-comparison",
        params={"category": "Professors"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin.status_code == 200
    assert faculty.json() == admin.json()


def test_faculty_category_breakdown_is_scoped(client, db_session):
    """/analytics/category takes a REQUIRED category, so it must be pinned
    too -- otherwise ?category=Staff returned the Staff breakdown outright."""
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/api/v1/analytics/category", params={"category": "Staff"}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    # Pinned to Professors: 2 rows, not the 1 Staff row that was seeded.
    assert body["category"] == "Professors"
    assert body["breakdown"]["total"] == 2


def test_faculty_word_frequency_is_scoped(client, db_session):
    """The word-frequency panel had no category filter at all, so it was the
    one analytics route where a faculty token could read the vocabulary of
    another department's feedback.

    Compared against an admin request pinned to Professors, so the assertion is
    about the scoping rather than about the seeded comment text.
    """
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    faculty = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Negative", "top_n": 20, "category": "Staff"},
        headers=headers,
    )
    assert faculty.status_code == 200

    admin_token = _register_admin_and_login(
        client, email="wf_scope_admin@asiatech.edu.ph"
    )
    admin = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Negative", "top_n": 20, "category": "Professors"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin.status_code == 200
    assert faculty.json() == admin.json()


def test_admin_word_frequency_still_sees_every_category(client, db_session):
    """The fix must not silently narrow administrators: no category still
    means every category for an admin."""
    admin = _register_admin_and_login(client, email="wf_all_admin@asiatech.edu.ph")
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {admin}"}

    unscoped = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Negative", "top_n": 50},
        headers=headers,
    ).json()
    scoped = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Negative", "top_n": 50, "category": "Professors"},
        headers=headers,
    ).json()

    # Negative rows were seeded in all four categories, so Professors alone is
    # a strict subset of the unscoped total.
    assert sum(w["count"] for w in scoped["words"]) < sum(
        w["count"] for w in unscoped["words"]
    )


def test_every_analytics_route_pins_the_faculty_scope():
    """Structural guard: no analytics route may accept a `category` and then
    forward it unscoped.

    The bypass existed precisely because applying the scope was a manual step
    at each of a dozen call sites, and five of them were forgotten. This walks
    the route table and fails if any handler takes a category parameter without
    referencing _scoped_category, so a newly added endpoint cannot silently
    reintroduce the leak.
    """
    import inspect

    from app.api import analytics as analytics_api

    offenders = []
    for route in analytics_api.router.routes:
        fn = getattr(route, "endpoint", None)
        if fn is None:
            continue
        try:
            names = set(inspect.signature(fn).parameters)
            source = inspect.getsource(fn)
        except (TypeError, ValueError, OSError):
            continue
        if "category" not in names:
            continue
        if "_scoped_category" not in source:
            offenders.append(f"{sorted(route.methods)[0]} {route.path}")

    assert not offenders, (
        "analytics routes that accept a category but do not scope it: "
        + ", ".join(offenders)
    )


def test_faculty_top_comments_are_scoped_to_professors(client, db_session):
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    complaints = client.get(
        "/api/v1/analytics/top-complaints", params={"limit": 10}, headers=headers
    )
    assert complaints.status_code == 200
    assert [item["category"] for item in complaints.json()["items"]] == ["Professors"]

    appreciations = client.get(
        "/api/v1/analytics/top-appreciations", params={"limit": 10}, headers=headers
    )
    assert appreciations.status_code == 200
    assert [item["category"] for item in appreciations.json()["items"]] == ["Professors"]


def test_faculty_course_analytics_is_scoped_to_professors(client, db_session):
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)

    response = client.get(
        "/api/v1/analytics/courses", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    # BSCS is the only program that appears on a Professors row; BSIT only
    # appears on Staff / Facilities / Payments rows, so it is filtered out.
    assert [p["course"] for p in response.json()["points"]] == ["BSCS"]


def test_admin_analytics_still_sees_every_category(client, db_session):
    token = _register_admin_and_login(client, email="scoped_admin@asiatech.edu.ph")
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    monthly = client.get("/api/v1/analytics/monthly", headers=headers)
    assert monthly.status_code == 200
    assert [p["total"] for p in monthly.json()["points"]] == [5]

    complaints = client.get(
        "/api/v1/analytics/top-complaints", params={"limit": 10}, headers=headers
    )
    assert complaints.status_code == 200
    assert len(complaints.json()["items"]) == 4
    assert {item["category"] for item in complaints.json()["items"]} == {
        "Professors", "Staff", "Facilities", "Payments",
    }

    # An admin may still narrow the panel explicitly.
    staff_only = client.get(
        "/api/v1/analytics/top-complaints",
        params={"limit": 10, "category": "Staff"},
        headers=headers,
    )
    assert staff_only.status_code == 200
    assert [item["category"] for item in staff_only.json()["items"]] == ["Staff"]

    courses = client.get("/api/v1/analytics/courses", headers=headers)
    assert courses.status_code == 200
    assert sorted(p["course"] for p in courses.json()["points"]) == ["BSCS", "BSIT"]

def test_faculty_csv_export_is_scoped_to_professors(client, db_session):
    """The 'Download Report' button lives on the faculty dashboard, so the
    export must be pinned to Professors too — otherwise it is a back door to
    the other three categories' raw comments."""
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)

    response = client.get(
        "/api/v1/analytics/export/csv", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.text
    assert "scope-prof-neg" in body
    for hidden in ("scope-staff", "scope-facilities", "scope-payments"):
        assert hidden not in body
    # Every exported row is a Professors row.
    data_rows = body.strip().splitlines()[1:]
    assert data_rows and {r.split(",")[1] for r in data_rows} == {"Professors"}


def test_admin_csv_export_still_includes_every_category(client, db_session):
    token = _register_admin_and_login(client, email="scoped_export_admin@asiatech.edu.ph")
    _seed_mixed_categories(db_session)

    response = client.get(
        "/api/v1/analytics/export/csv", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    for expected in ("scope-prof-neg", "scope-staff", "scope-facilities", "scope-payments"):
        assert expected in response.text


# ============================================================
# Likert panels — "Rating Distribution" (1-5 histogram) and
# "Average by Aspect" (per-aspect means), both faculty-facing.
#
# The 1-5 signal is stored per submission (Evaluation.likert_average
# and Evaluation.ratings), so these are aggregations over existing
# data. Like the rest of the faculty dashboard they must be scoped
# to Professors only.
# ============================================================


def _seed_likert_rows(db_session):
    """Three rated Professors rows spanning the 1-5 range, one unrated
    comment-only Professors row, and one rated Staff row that must never
    reach a faculty account."""
    _seed_evaluation(
        db_session, evaluation_id="likert-prof-5", category="Professors",
        sentiment="Positive", likert_average=5.0,
        ratings={"mastery": 5, "clarity": 5, "punctuality": 4, "approachability": 5},
        created_at=datetime(2026, 7, 15, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="likert-prof-4", category="Professors",
        sentiment="Positive", likert_average=4.0,
        ratings={"mastery": 4, "clarity": 5, "punctuality": 3, "approachability": 4},
        created_at=datetime(2026, 7, 16, 9, 0, 0),
    )
    _seed_evaluation(
        db_session, evaluation_id="likert-prof-2", category="Professors",
        sentiment="Negative", likert_average=2.0,
        ratings={"mastery": 2, "clarity": 2, "punctuality": 3, "approachability": 1},
        created_at=datetime(2026, 7, 17, 9, 0, 0),
    )
    # Comment-only submission: no Likert answer, so it must not be bucketed.
    _seed_evaluation(
        db_session, evaluation_id="likert-prof-unrated", category="Professors",
        sentiment="Neutral", created_at=datetime(2026, 7, 18, 9, 0, 0),
    )
    # Other category: excluded from every faculty panel.
    _seed_evaluation(
        db_session, evaluation_id="likert-staff-1", category="Staff",
        sentiment="Negative", likert_average=1.0,
        ratings={"safety": 1, "registrar": 2},
        created_at=datetime(2026, 7, 19, 9, 0, 0),
    )


def test_rating_distribution_buckets_professors_only(client, db_session):
    """All five bands are always present; faculty see only Professors rows and
    the unrated comment-only row is not counted as a rating."""
    token = _login_faculty(client)
    _seed_likert_rows(db_session)

    response = client.get(
        "/api/v1/analytics/ratings/distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()

    assert [p["band"] for p in data["points"]] == [1, 2, 3, 4, 5]
    by_band = {p["band"]: p for p in data["points"]}
    assert by_band[5]["total"] == 1
    assert by_band[4]["total"] == 1
    assert by_band[2]["total"] == 1
    # Bands 1 and 3 stay on the axis but empty: band 1's only submission is a
    # Staff row the faculty account may not see.
    assert by_band[1]["total"] == 0
    assert by_band[3]["total"] == 0
    # The comment-only row contributes no rating.
    assert data["total"] == 3
    assert data["average"] == 3.67          # (5 + 4 + 2) / 3
    # Each band carries the sentiment split so the chart can stack.
    assert by_band[2]["negative"] == 1
    assert by_band[4]["positive"] == 1
    assert by_band[5]["positive"] == 1
    assert by_band[5]["label"] == "Strongly agree"


def test_aspect_averages_are_professors_only_and_sorted(client, db_session):
    token = _login_faculty(client)
    _seed_likert_rows(db_session)

    response = client.get(
        "/api/v1/analytics/ratings/aspects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    points = response.json()["points"]

    aspects = [p["aspect"] for p in points]
    # No Staff aspects leak through.
    assert "safety" not in aspects
    assert "registrar" not in aspects
    # Strongest first — the order the horizontal bar chart plots.
    averages = [p["average"] for p in points]
    assert averages == sorted(averages, reverse=True)
    assert aspects[0] == "clarity"
    assert dict(zip(aspects, averages)) == {
        "clarity": 4.0,          # (5 + 5 + 2) / 3
        "mastery": 3.67,         # (5 + 4 + 2) / 3
        "approachability": 3.33, # (5 + 4 + 1) / 3
        "punctuality": 3.33,     # (4 + 3 + 3) / 3
    }
    # Human labels, not raw keys.
    labels = {p["aspect"]: p["label"] for p in points}
    assert labels["clarity"] == "Clarity of explanation"
    assert labels["mastery"] == "Subject mastery"
    # Response count is reported so a thin average reads as thin.
    assert all(p["responses"] == 3 for p in points)



def test_faculty_cannot_widen_likert_panels(client, db_session):
    """Hand-crafting ?category=Staff is pinned back to Professors, like the
    other faculty panels."""
    token = _login_faculty(client)
    _seed_likert_rows(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    distribution = client.get(
        "/api/v1/analytics/ratings/distribution",
        params={"category": "Staff"},
        headers=headers,
    )
    assert distribution.json()["total"] == 3

    aspects = client.get(
        "/api/v1/analytics/ratings/aspects",
        params={"category": "Staff"},
        headers=headers,
    )
    assert "safety" not in [p["aspect"] for p in aspects.json()["points"]]


def test_faculty_overall_is_scoped_to_professors(client, db_session):
    """The sentiment-split doughnut reads /overall, which must be pinned too."""
    token = _login_faculty(client)
    _seed_mixed_categories(db_session)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/v1/analytics/overall", headers=headers)
    assert response.status_code == 200
    data = response.json()
    # _seed_mixed_categories: 2 Professors rows + 1 each Staff/Facilities/Payments.
    assert data["breakdown"]["total"] == 2
    assert data["evaluation_volume"] == 2

    asked_for_staff = client.get(
        "/api/v1/analytics/overall", params={"category": "Staff"}, headers=headers
    )
    assert asked_for_staff.json()["breakdown"]["total"] == 2


def test_admin_still_sees_likert_data_from_every_category(client, db_session):
    token = _register_admin_and_login(client, email="likert_admin@asiatech.edu.ph")
    _seed_likert_rows(db_session)

    distribution = client.get(
        "/api/v1/analytics/ratings/distribution",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert distribution.status_code == 200
    data = distribution.json()
    # The Staff row is visible to an admin, so band 1 is populated and the
    # total is one higher than the faculty view.
    assert {p["band"]: p["total"] for p in data["points"]}[1] == 1
    assert data["total"] == 4

    aspects = client.get(
        "/api/v1/analytics/ratings/aspects",
        headers={"Authorization": f"Bearer {token}"},
    )
    admin_aspects = {p["aspect"]: p["average"] for p in aspects.json()["points"]}
    assert admin_aspects["safety"] == 1.0
    assert admin_aspects["registrar"] == 2.0
    # Weakest aspect sorts last, so the bar chart puts it at the bottom.
    assert aspects.json()["points"][-1]["aspect"] == "safety"


def test_likert_analytics_ignore_malformed_values(client, db_session):
    """A junk or out-of-range value is skipped, not fatal — the dashboard must
    still render. An aspect key with no display-name entry falls back to a
    readable title-cased label."""
    token = _login_faculty(client)
    _seed_evaluation(
        db_session, evaluation_id="likert-junk", category="Professors",
        sentiment="Neutral", likert_average=9.0,   # outside the 1-5 scale
        ratings={"clarity": "not-a-number", "mastery": 4, "punctuality": 99},
        created_at=datetime(2026, 7, 20, 9, 0, 0),
    )
    headers = {"Authorization": f"Bearer {token}"}

    distribution = client.get(
        "/api/v1/analytics/ratings/distribution", headers=headers
    )
    assert distribution.status_code == 200
    assert distribution.json()["total"] == 0

    aspects = client.get("/api/v1/analytics/ratings/aspects", headers=headers)
    assert aspects.status_code == 200
    points = aspects.json()["points"]
    # Only the one valid key survives; the other two are dropped.
    assert [p["aspect"] for p in points] == ["mastery"]
    assert points[0]["label"] == "Subject mastery"

