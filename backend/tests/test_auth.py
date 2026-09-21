"""Auth flow tests — institution-only sign-in.

Public registration was removed: admin/faculty accounts are provisioned
by seed_admin.py (or an internal admin panel), login is gated to
@asiatech.edu.ph addresses, and login reports whether the account still
uses its seed default password. Students are anonymous and never sign in.
"""
from app.core.security import hash_password
from app.models.user import User, UserRole

DEFAULT_ADMIN_PASSWORD = "ASIATECH-admin123"
DEFAULT_FACULTY_PASSWORD = "ASIATECH-faculty123"


def _make_user(db_session, email, password, role, full_name="Test User"):
    user = User(
        full_name=full_name,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_register_endpoint_removed(client):
    """There is no public sign-up anymore."""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Some One",
            "email": "some@asiatech.edu.ph",
            "password": "SecurePass123",
            "role": "administrator",
        },
    )
    assert response.status_code in (404, 405)


def test_login_rejects_non_institution_domain(client, db_session):
    _make_user(db_session, "outsider@gmail.com", "SecurePass123", UserRole.ADMINISTRATOR)
    response = client.post(
        "/api/v1/auth/login", json={"email": "outsider@gmail.com", "password": "SecurePass123"}
    )
    assert response.status_code == 403
    assert "asiatech.edu.ph" in response.json()["detail"]


def test_login_domain_check_is_case_insensitive(client, db_session):
    # Emails are stored lowercase (as seed_admin.py does), but a user may type
    # the domain in any case. Pydantic's EmailStr normalizes the domain part to
    # lowercase, so a mixed-case domain must still authenticate successfully.
    _make_user(db_session, "admin@asiatech.edu.ph", "SecurePass123", UserRole.ADMINISTRATOR)
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin@AsiaTech.EDU.PH", "password": "SecurePass123"}
    )
    assert response.status_code == 200


def test_admin_login_flags_default_password(client, db_session):
    _make_user(
        db_session, "admin@asiatech.edu.ph", DEFAULT_ADMIN_PASSWORD,
        UserRole.ADMINISTRATOR, "Admin User",
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@asiatech.edu.ph", "password": DEFAULT_ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["using_default_password"] is True
    assert data["user"]["role"] == "administrator"
    assert data["access_token"]
    assert data["refresh_token"]


def test_faculty_login_flags_default_password(client, db_session):
    _make_user(
        db_session, "faculty@asiatech.edu.ph", DEFAULT_FACULTY_PASSWORD,
        UserRole.FACULTY, "Faculty User",
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "faculty@asiatech.edu.ph", "password": DEFAULT_FACULTY_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["using_default_password"] is True


def test_custom_password_not_flagged_as_default(client, db_session):
    _make_user(db_session, "admin2@asiatech.edu.ph", "CustomPass123", UserRole.ADMINISTRATOR)
    response = client.post(
        "/api/v1/auth/login", json={"email": "admin2@asiatech.edu.ph", "password": "CustomPass123"}
    )
    assert response.status_code == 200
    assert response.json()["using_default_password"] is False


def test_login_with_wrong_password_fails(client, db_session):
    _make_user(db_session, "maria@asiatech.edu.ph", "SecurePass123", UserRole.FACULTY)
    response = client.post(
        "/api/v1/auth/login", json={"email": "maria@asiatech.edu.ph", "password": "WrongPassword"}
    )
    assert response.status_code == 401


def test_login_unknown_user_fails(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@asiatech.edu.ph", "password": "SecurePass123"},
    )
    assert response.status_code == 401


def test_inactive_account_cannot_log_in(client, db_session):
    user = _make_user(
        db_session, "deactivated@asiatech.edu.ph", "SecurePass123", UserRole.ADMINISTRATOR
    )
    user.is_active = False
    db_session.commit()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "deactivated@asiatech.edu.ph", "password": "SecurePass123"},
    )
    assert response.status_code == 403


def test_refresh_token_flow(client, db_session):
    _make_user(db_session, "refresh@asiatech.edu.ph", "SecurePass123", UserRole.FACULTY)
    login = client.post(
        "/api/v1/auth/login", json={"email": "refresh@asiatech.edu.ph", "password": "SecurePass123"}
    )
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]


def test_get_me_requires_auth(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_forgot_password_unknown_email_returns_200(client):
    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nonexistent@asiatech.edu.ph"},
    )
    assert response.status_code == 200
    assert "reset_token" not in response.json()


def test_forgot_password_returns_token(client, db_session):
    _make_user(db_session, "reset@asiatech.edu.ph", "SecurePass123", UserRole.ADMINISTRATOR)
    response = client.post("/api/v1/auth/forgot-password", json={"email": "reset@asiatech.edu.ph"})
    assert response.status_code == 200
    assert response.json().get("reset_token")


def test_reset_password_flow(client, db_session):
    _make_user(db_session, "flow@asiatech.edu.ph", "OldPass123", UserRole.FACULTY)
    forgot = client.post("/api/v1/auth/forgot-password", json={"email": "flow@asiatech.edu.ph"})
    token = forgot.json()["reset_token"]

    reset = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "NewPass456"}
    )
    assert reset.status_code == 200

    # Old password should fail
    old_login = client.post(
        "/api/v1/auth/login", json={"email": "flow@asiatech.edu.ph", "password": "OldPass123"}
    )
    assert old_login.status_code == 401

    # New password should work and not be flagged as a default password
    new_login = client.post(
        "/api/v1/auth/login", json={"email": "flow@asiatech.edu.ph", "password": "NewPass456"}
    )
    assert new_login.status_code == 200
    assert new_login.json()["using_default_password"] is False


def test_reset_password_invalid_token(client):
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "NewPass456"},
    )
    assert response.status_code == 400


def test_get_profile_requires_auth(client):
    response = client.get("/api/v1/auth/me/profile")
    assert response.status_code == 401


def test_update_profile(client, db_session):
    _make_user(db_session, "profile@asiatech.edu.ph", "SecurePass123", UserRole.ADMINISTRATOR)
    login = client.post(
        "/api/v1/auth/login", json={"email": "profile@asiatech.edu.ph", "password": "SecurePass123"}
    )
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


def test_update_profile_change_password(client, db_session):
    _make_user(db_session, "passchange@asiatech.edu.ph", "SecurePass123", UserRole.FACULTY)
    login = client.post(
        "/api/v1/auth/login", json={"email": "passchange@asiatech.edu.ph", "password": "SecurePass123"}
    )
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

    # Login with new password — no longer flagged as default
    new_login = client.post(
        "/api/v1/auth/login", json={"email": "passchange@asiatech.edu.ph", "password": "NewPass456"}
    )
    assert new_login.status_code == 200
    assert new_login.json()["using_default_password"] is False
