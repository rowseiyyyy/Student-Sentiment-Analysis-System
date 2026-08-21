def test_register_and_login(client):
    register_payload = {
        "full_name": "Juan Dela Cruz",
        "email": "juan@example.com",
        "password": "SecurePass123",
        "role": "student",
    }
    response = client.post("/api/v1/auth/register", json=register_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "juan@example.com"
    assert "id" in data

    login_response = client.post(
        "/api/v1/auth/login", json={"email": "juan@example.com", "password": "SecurePass123"}
    )
    assert login_response.status_code == 200
    token_data = login_response.json()
    assert "access_token" in token_data
    assert token_data["user"]["email"] == "juan@example.com"


def test_login_with_wrong_password_fails(client):
    client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Maria Santos",
            "email": "maria@example.com",
            "password": "SecurePass123",
            "role": "student",
        },
    )
    response = client.post(
        "/api/v1/auth/login", json={"email": "maria@example.com", "password": "WrongPassword"}
    )
    assert response.status_code == 401


def test_duplicate_registration_fails(client):
    payload = {
        "full_name": "Pedro Reyes",
        "email": "pedro@example.com",
        "password": "SecurePass123",
        "role": "student",
    }
    first = client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


def test_get_me_requires_auth(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_forgot_password_unknown_email_returns_200(client):
    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nonexistent@example.com"},
    )
    assert response.status_code == 200
    assert "reset_token" not in response.json()


def test_forgot_password_returns_token(client):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Reset User", "email": "reset@example.com", "password": "SecurePass123", "role": "student"},
    )
    response = client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
    assert response.status_code == 200
    data = response.json()
    assert "reset_token" in data
    assert data["reset_token"]


def test_reset_password_flow(client):
    # Register and login
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Flow User", "email": "flow@example.com", "password": "OldPass123", "role": "student"},
    )
    forgot = client.post("/api/v1/auth/forgot-password", json={"email": "flow@example.com"})
    token = forgot.json()["reset_token"]

    reset = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "NewPass456"})
    assert reset.status_code == 200

    # Old password should fail
    old_login = client.post("/api/v1/auth/login", json={"email": "flow@example.com", "password": "OldPass123"})
    assert old_login.status_code == 401

    # New password should work
    new_login = client.post("/api/v1/auth/login", json={"email": "flow@example.com", "password": "NewPass456"})
    assert new_login.status_code == 200


def test_reset_password_invalid_token(client):
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "NewPass456"},
    )
    assert response.status_code == 400


def test_get_profile_requires_auth(client):
    response = client.get("/api/v1/auth/me/profile")
    assert response.status_code == 401


def test_update_profile(client):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Profile User", "email": "profile@example.com", "password": "SecurePass123", "role": "student"},
    )
    login = client.post("/api/v1/auth/login", json={"email": "profile@example.com", "password": "SecurePass123"})
    token = login.json()["access_token"]

    response = client.put(
        "/api/v1/auth/me/profile",
        json={"full_name": "Updated Name", "course": "BSIT", "year_level": "3rd Year", "student_id": "1-2345"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Updated Name"
    assert data["course"] == "BSIT"


def test_update_profile_change_password(client):
    client.post(
        "/api/v1/auth/register",
        json={"full_name": "Pass Change", "email": "passchange@example.com", "password": "SecurePass123", "role": "student"},
    )
    login = client.post("/api/v1/auth/login", json={"email": "passchange@example.com", "password": "SecurePass123"})
    token = login.json()["access_token"]

    # Incorrect current password fails
    bad = client.put(
        "/api/v1/auth/me/profile",
        json={"current_password": "wrong", "new_password": "NewPass456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad.status_code == 400

    # Correct current password works
    good = client.put(
        "/api/v1/auth/me/profile",
        json={"current_password": "SecurePass123", "new_password": "NewPass456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert good.status_code == 200

    # Login with new password
    new_login = client.post("/api/v1/auth/login", json={"email": "passchange@example.com", "password": "NewPass456"})
    assert new_login.status_code == 200
