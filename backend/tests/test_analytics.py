def _register_admin_and_login(client, email="admin_analytics@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Admin Analytics",
            "email": email,
            "password": "SecurePass123",
            "role": "administrator",
        },
    )
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
    token = _register_admin_and_login(client, email="admin_analytics2@example.com")
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
    token = _register_admin_and_login(client, email="monthly_admin@example.com")
    response = client.get("/api/v1/analytics/monthly", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "points" in data


def test_daily_trend_empty_db(client):
    token = _register_admin_and_login(client, email="daily_admin@example.com")
    response = client.get("/api/v1/analytics/daily", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "points" in data


def test_word_frequency_requires_valid_sentiment(client):
    token = _register_admin_and_login(client, email="wf_admin@example.com")
    response = client.get(
        "/api/v1/analytics/word-frequency",
        params={"sentiment": "Positive", "top_n": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "words" in response.json()


def test_top_complaints_and_appreciations_empty(client):
    token = _register_admin_and_login(client, email="tc_admin@example.com")
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

    token = _register_admin_and_login(client, email="csvdata_admin@example.com")
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
