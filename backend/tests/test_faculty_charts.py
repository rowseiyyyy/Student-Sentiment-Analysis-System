"""Faculty chart visibility: the admin-managed sharing map, enforced server-side.

Covers the three acceptance rules:

* On first deploy (no saved row) every existing faculty chart is visible.
* A chart added to the registry later defaults to HIDDEN until enabled.
* Faculty chart *data* endpoints answer 403 for a disabled chart, for every
  faculty chart, while administrators are never gated — and the CSV export
  applies the same map column-by-column (403 when nothing is shared).

The map is global: saving once changes what every faculty account gets, and
the change survives new sessions (it lives in the database, not the token).
"""

import uuid
from datetime import datetime

# ============================================================
# Helpers
# ============================================================

VISIBILITY_URL = "/api/v1/analytics/faculty-charts"
ALL_CHART_KEYS = [
    "sentiment_split",
    "rating_distribution",
    "aspect_averages",
    "sentiment_courses",
    "top_comments",
]


def _login(client, *, role, email, full_name):
    client.make_user(email, role=role, full_name=full_name)
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    return login.json()["access_token"]


def _admin(client, email="vis_admin@asiatech.edu.ph"):
    return _login(client, role="administrator", email=email, full_name="Visibility Admin")


def _faculty(client, email="vis_faculty@asiatech.edu.ph"):
    return _login(client, role="faculty", email=email, full_name="Visibility Faculty")


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _save(client, token, charts):
    return client.put(VISIBILITY_URL, json={"charts": charts}, headers=_headers(token))


def _visible_map(client, token):
    response = client.get(VISIBILITY_URL, headers=_headers(token))
    assert response.status_code == 200
    return {c["key"]: c["visible"] for c in response.json()["charts"]}


def _seed_evaluation(db_session, *, evaluation_id, category, sentiment, created_at, course=None):
    """One evaluation + prediction row, so the CSV export has content."""
    from app.models.evaluation import Evaluation, EvaluationCategory
    from app.models.prediction import AlgorithmName, Prediction, SentimentLabel

    db_session.add(
        Evaluation(
            id=evaluation_id,
            category=EvaluationCategory(category),
            comment=f"Comment for {evaluation_id}",
            course=course,
            created_at=created_at,
        )
    )
    db_session.add(
        Prediction(
            evaluation_id=evaluation_id,
            official_prediction=SentimentLabel(sentiment),
            algorithm_used=AlgorithmName.MBERT_HYBRID,
            confidence_score=0.9,
            processing_time_ms=12.0,
            created_at=created_at,
        )
    )
    db_session.commit()


# ============================================================
# Registry / defaults
# ============================================================

def test_defaults_are_all_visible_before_anything_is_saved(client):
    """First deploy: no row exists, so every existing chart stays visible —
    for administrators and for faculty alike."""
    admin = _admin(client)
    faculty = _faculty(client)

    admin_view = _visible_map(client, admin)
    faculty_view = _visible_map(client, faculty)

    assert set(admin_view) == set(ALL_CHART_KEYS)
    assert all(admin_view.values())
    assert faculty_view == admin_view


def test_metadata_endpoint_lists_labels_in_registry_order(client):
    token = _admin(client)
    response = client.get(VISIBILITY_URL, headers=_headers(token))
    charts = response.json()["charts"]
    assert [c["key"] for c in charts] == ALL_CHART_KEYS
    assert all(c["label"] for c in charts)


def test_new_chart_in_registry_defaults_to_hidden(client, monkeypatch):
    """A chart shipped AFTER the last save must not appear for faculty until
    an admin turns it on — no stored value falls back to its default."""
    from app.services import faculty_charts as registry

    admin = _admin(client)
    # Simulate the admin panel's normal save while the future chart does not
    # exist yet: the stored map only covers today's keys.
    assert _save(client, admin, {key: True for key in ALL_CHART_KEYS}).status_code == 200

    monkeypatch.setitem(registry.FACULTY_CHARTS, "future_panel", ("Future Panel", False))

    view = _visible_map(client, _faculty(client, email="future_faculty@asiatech.edu.ph"))
    assert view["future_panel"] is False
    # The pre-existing charts are untouched by the new key.
    assert view["sentiment_split"] is True


def test_unknown_chart_key_is_rejected(client):
    token = _admin(client)
    response = _save(client, token, {"no_such_chart": True})
    assert response.status_code == 400
    assert "no_such_chart" in response.json()["detail"]


def test_faculty_cannot_save_the_map(client):
    """Enforced server-side, not by hiding the button."""
    token = _faculty(client)
    response = _save(client, token, {"sentiment_split": False})
    assert response.status_code == 403


def test_student_cannot_read_the_map(client):
    client.make_user("vis_student@asiatech.edu.ph", role="student", full_name="Student")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "vis_student@asiatech.edu.ph", "password": "SecurePass123"},
    )
    response = client.get(VISIBILITY_URL, headers=_headers(login.json()["access_token"]))
    assert response.status_code == 403


def test_save_persists_across_sessions(client):
    """The map is global and database-backed: a later session (fresh login,
    as after a reload or logout) reads back exactly what was saved."""
    admin = _admin(client)
    saved = _save(client, admin, {"sentiment_split": False, "top_comments": False})
    assert saved.status_code == 200

    # Fresh login, i.e. nothing carried in the token or the client.
    later = _faculty(client, email="later_faculty@asiatech.edu.ph")
    view = _visible_map(client, later)
    assert view["sentiment_split"] is False
    assert view["top_comments"] is False
    assert view["rating_distribution"] is True


# ============================================================
# Endpoint gating — every faculty chart's backing route
# ============================================================

# chart key -> (path, params) for every endpoint that feeds a faculty chart.
GATED_ROUTES = [
    ("sentiment_split", "/api/v1/analytics/overall", {}),
    ("rating_distribution", "/api/v1/analytics/ratings/distribution", {}),
    ("aspect_averages", "/api/v1/analytics/ratings/aspects", {}),
    ("sentiment_courses", "/api/v1/analytics/courses", {}),
    ("top_comments", "/api/v1/analytics/top-complaints", {"limit": 5}),
    ("top_comments", "/api/v1/analytics/top-appreciations", {"limit": 5}),
]


def test_disabled_chart_endpoint_forbids_faculty_and_still_serves_admin(client):
    """Per route: disable its chart, faculty gets 403, admin still gets 200."""
    admin = _admin(client)
    faculty = _faculty(client)

    for key, path, params in GATED_ROUTES:
        # Disable exactly this chart (a partial save; missing keys keep their
        # defaults), so each iteration is independent of the others.
        assert _save(client, admin, {key: False}).status_code == 200

        as_faculty = client.get(path, params=params, headers=_headers(faculty))
        assert as_faculty.status_code == 403, f"{path} must be gated for faculty"
        assert "shared with faculty" in as_faculty.json()["detail"]

        as_admin = client.get(path, params=params, headers=_headers(admin))
        assert as_admin.status_code == 200, f"{path} must never gate an administrator"

        # Re-enable so the next iteration starts from a clean slate.
        assert _save(client, admin, {key: True}).status_code == 200
        assert client.get(path, params=params, headers=_headers(faculty)).status_code == 200


def test_all_charts_disabled_forbids_every_faculty_data_endpoint(client):
    """Nothing shared: every faculty chart data endpoint answers 403."""
    admin = _admin(client)
    faculty = _faculty(client)
    _save(client, admin, {key: False for key in ALL_CHART_KEYS})

    for _key, path, params in GATED_ROUTES:
        response = client.get(path, params=params, headers=_headers(faculty))
        assert response.status_code == 403, path


def test_enabled_chart_does_not_block_its_neighbours(client):
    """Each case: one chart disabled, its neighbours keep serving 200."""
    admin = _admin(client)
    faculty = _faculty(client)

    others = {
        "sentiment_split": "/api/v1/analytics/ratings/distribution",
        "rating_distribution": "/api/v1/analytics/overall",
        "aspect_averages": "/api/v1/analytics/courses",
        "sentiment_courses": "/api/v1/analytics/top-complaints",
        "top_comments": "/api/v1/analytics/overall",
    }
    for key, neighbour in others.items():
        assert _save(client, admin, {key: False}).status_code == 200
        response = client.get(neighbour, headers=_headers(faculty))
        assert response.status_code == 200, (key, neighbour)
        assert _save(client, admin, {key: True}).status_code == 200


def test_faculty_preview_mode_is_an_admin_token_and_is_not_gated(client):
    """The admin's 'preview the faculty view' passes an admin token, so it
    keeps working no matter what the map says."""
    admin = _admin(client)
    _save(client, admin, {key: False for key in ALL_CHART_KEYS})

    response = client.get("/api/v1/analytics/overall", headers=_headers(admin))
    assert response.status_code == 200


# ============================================================
# CSV export — same map, applied column-by-column
# ============================================================

def _seed_report_row(db_session):
    _seed_evaluation(
        db_session,
        evaluation_id=f"vis-{uuid.uuid4().hex[:8]}",
        category="Professors",
        sentiment="Negative",
        course="BSCS",
        created_at=datetime(2026, 7, 15, 9, 0, 0),
    )


def _csv_header(response):
    assert response.status_code == 200
    return response.text.splitlines()[0].split(",")


def test_csv_drops_comment_column_when_top_comments_disabled(client, db_session):
    admin = _admin(client)
    faculty = _faculty(client)
    _seed_report_row(db_session)
    _save(client, admin, {"top_comments": False})

    response = client.get("/api/v1/analytics/export/csv", headers=_headers(faculty))
    header = _csv_header(response)
    assert "comment" not in header
    # The columns that remain keep their original order.
    assert header[0] == "evaluation_id" and header[1] == "category"
    assert "created_at" in header
    # And no comment text leaks through in the body either.
    body = response.text
    assert "Comment for" not in body


def test_csv_drops_sentiment_and_prediction_columns_when_split_disabled(client, db_session):
    admin = _admin(client)
    faculty = _faculty(client)
    _seed_report_row(db_session)
    _save(client, admin, {"sentiment_split": False})

    header = _csv_header(client.get("/api/v1/analytics/export/csv", headers=_headers(faculty)))
    for column in (
        "sentiment", "official_prediction", "algorithm_used", "confidence_score",
        "svm_prediction", "svm_confidence",
        "naive_bayes_prediction", "naive_bayes_confidence",
        "logistic_regression_prediction", "logistic_regression_confidence",
    ):
        assert column not in header, column
    # Top Comments is still shared, so the comment column survives.
    assert "comment" in header


def test_csv_is_403_for_faculty_when_nothing_is_shared(client):
    admin = _admin(client)
    faculty = _faculty(client)
    _save(client, admin, {key: False for key in ALL_CHART_KEYS})

    response = client.get("/api/v1/analytics/export/csv", headers=_headers(faculty))
    assert response.status_code == 403


def test_csv_for_admin_is_unchanged_whatever_the_map_says(client, db_session):
    """Strict for faculty, full export for administrators — the panel only
    governs what FACULTY accounts read."""
    admin = _admin(client)
    _seed_report_row(db_session)
    _save(client, admin, {key: False for key in ALL_CHART_KEYS})

    response = client.get("/api/v1/analytics/export/csv", headers=_headers(admin))
    header = _csv_header(response)
    expected = [
        "evaluation_id", "category", "comment", "sentiment", "official_prediction",
        "algorithm_used", "confidence_score", "svm_prediction", "svm_confidence",
        "naive_bayes_prediction", "naive_bayes_confidence",
        "logistic_regression_prediction", "logistic_regression_confidence",
        "created_at",
    ]
    assert header == expected
    assert "Comment for" in response.text


