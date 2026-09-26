def _login(client, email, role):
    client.make_user(email, role=role, full_name="Layout Tester")
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "SecurePass123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _admin(client):
    return _login(client, "layout_admin@asiatech.edu.ph", "administrator")


def _faculty(client):
    return _login(client, "layout_faculty@asiatech.edu.ph", "faculty")


def _student(client):
    return _login(client, "layout_student@asiatech.edu.ph", "student")


# ---------------------------------------------------------------- access ----


def test_layout_read_requires_authentication(client):
    response = client.get("/api/v1/dashboard-layout/admin_overview")
    assert response.status_code == 401


def test_student_cannot_read_layout(client):
    """Students have no dashboard to lay out."""
    response = client.get(
        "/api/v1/dashboard-layout/admin_overview", headers=_student(client)
    )
    assert response.status_code == 403


def test_faculty_can_read_layout(client):
    """Faculty render the finalized layout, so they need to read it."""
    response = client.get(
        "/api/v1/dashboard-layout/admin_analytics", headers=_faculty(client)
    )
    assert response.status_code == 200


def test_faculty_cannot_save_layout(client):
    """The access-control surface: enforced server-side, not by hiding a
    button. A faculty member crafting the PUT by hand gets a 403."""
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_faculty(client),
        json={"name": "admin_analytics", "widgets": {"analytics:x": {"w": 2, "h": 300}}},
    )
    assert response.status_code == 403


def test_student_cannot_save_layout(client):
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_student(client),
        json={"name": "admin_analytics", "widgets": {"analytics:x": {"w": 2, "h": 300}}},
    )
    assert response.status_code == 403


# ------------------------------------------------------------------ read ----


def test_unsaved_layout_reads_as_empty_not_an_error(client):
    """The first render of any dashboard has nothing saved. GET must be total,
    not a 404, or every page would break before the editor was ever opened."""
    response = client.get(
        "/api/v1/dashboard-layout/admin_overview", headers=_admin(client)
    )
    assert response.status_code == 200
    assert response.json()["widgets"] == {}


# -------------------------------------------------------------- save/read ----




def test_saving_twice_updates_in_place(client):
    """One row per name: a second save must replace, not accumulate, or
    readers would have two documents to arbitrate between."""
    admin = _admin(client)
    client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=admin,
        json={"name": "admin_analytics", "widgets": {"a": {"w": 1, "h": 200}}},
    )
    client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=admin,
        json={"name": "admin_analytics", "widgets": {"b": {"w": 2, "h": 300}}},
    )
    body = client.get("/api/v1/dashboard-layout/admin_analytics", headers=admin).json()
    assert set(body["widgets"]) == {"b"}


def test_body_name_must_match_path(client):
    """Writing to a layout other than the one addressed would be a confusing
    way to lose an edit."""
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_overview", "widgets": {}},
    )
    assert response.status_code == 400


# ------------------------------------------------------------- validation ----


def test_out_of_range_geometry_is_rejected(client):
    """A hand-crafted payload must not be able to store a size that renders
    unusably (a zero-height chart, a 100000px column)."""
    admin = _admin(client)
    for bad in (
        {"w": 0, "h": 300},
        {"w": 99, "h": 300},
        {"w": 2, "h": 5},
        {"w": 2, "h": 99999},
    ):
        response = client.put(
            "/api/v1/dashboard-layout/admin_analytics",
            headers=admin,
            json={"name": "admin_analytics", "widgets": {"x": bad}},
        )
        assert response.status_code == 422, f"accepted {bad}"


def test_height_is_rounded_to_a_ten_px_step(client):
    """A drag gesture should produce a tidy stored value, not an arbitrary
    pixel."""
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": {"x": {"w": 2, "h": 313}}},
    )
    assert response.json()["widgets"]["x"]["h"] == 310


def test_layout_name_charset_is_constrained(client):
    """Names go into a path segment, so the charset is restricted."""
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "bad name/../etc", "widgets": {}},
    )
    assert response.status_code == 422


def test_widget_count_is_capped(client):
    """One request must not be able to write an unbounded document."""
    widgets = {f"w{i}": {"w": 1, "h": 200} for i in range(500)}
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": widgets},
    )
    assert response.status_code == 422


# ----------------------------------------------------------------- order ----


def test_order_round_trips(client):
    """Reordering within a section is stored and read back: the point of the
    feature is that the admin's arrangement survives a reload."""
    admin = _admin(client)
    faculty = _faculty(client)
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=admin,
        json={
            "name": "admin_analytics",
            "widgets": {
                "analytics:chart-b": {"w": 1, "h": 300, "order": 0},
                "analytics:chart-a": {"w": 1, "h": 300, "order": 1},
            },
        },
    )
    assert response.status_code == 200
    read = client.get("/api/v1/dashboard-layout/admin_analytics", headers=faculty)
    assert read.json()["widgets"]["analytics:chart-b"]["order"] == 0
    assert read.json()["widgets"]["analytics:chart-a"]["order"] == 1


def test_order_is_optional_for_back_compatible_rows(client):
    """A layout saved before reordering existed has no order. It must still be
    accepted and read back as null, not rejected -- otherwise adding this field
    would invalidate every layout already saved."""
    admin = _admin(client)
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=admin,
        json={"name": "admin_analytics", "widgets": {"a": {"w": 2, "h": 300}}},
    )
    assert response.status_code == 200
    assert response.json()["widgets"]["a"]["order"] is None


def test_negative_order_is_rejected(client):
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": {"a": {"w": 1, "h": 300, "order": -1}}},
    )
    assert response.status_code == 422


def test_absurd_order_is_rejected(client):
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": {"a": {"w": 1, "h": 300, "order": 99999}}},
    )
    assert response.status_code == 422


# ------------------------------------------------------- widened geometry ----


def test_full_width_and_tall_height_are_accepted(client):
    """The editor now offers up to 6 columns and 1600px, so the server's old
    4-column cap would have rejected a legitimate drag."""
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={
            "name": "admin_analytics",
            "widgets": {
                "wide": {"w": 6, "h": 1600, "order": 0},
                "small": {"w": 1, "h": 120, "order": 1},
            },
        },
    )
    assert response.status_code == 200
    widgets = response.json()["widgets"]
    assert widgets["wide"] == {"w": 6, "h": 1600, "order": 0}
    assert widgets["small"]["h"] == 120


def test_width_above_six_is_still_rejected(client):
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": {"a": {"w": 7, "h": 300}}},
    )
    assert response.status_code == 422


def test_height_above_1600_is_still_rejected(client):
    response = client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=_admin(client),
        json={"name": "admin_analytics", "widgets": {"a": {"w": 1, "h": 2000}}},
    )
    assert response.status_code == 422


# ------------------------------------------------------------------ reset ----


def test_reset_deletes_the_layout(client):
    """Reset must delete rather than save an empty document, so a later "no
    saved layout" is genuinely the default."""
    admin = _admin(client)
    client.put(
        "/api/v1/dashboard-layout/admin_analytics",
        headers=admin,
        json={"name": "admin_analytics", "widgets": {"x": {"w": 2, "h": 300}}},
    )
    deleted = client.delete("/api/v1/dashboard-layout/admin_analytics", headers=admin)
    assert deleted.status_code == 204

    body = client.get("/api/v1/dashboard-layout/admin_analytics", headers=admin).json()
    assert body["widgets"] == {}


def test_faculty_cannot_reset(client):
    response = client.delete(
        "/api/v1/dashboard-layout/admin_analytics", headers=_faculty(client)
    )
    assert response.status_code == 403


def test_reset_of_never_saved_layout_is_a_no_op(client):
    response = client.delete(
        "/api/v1/dashboard-layout/admin_analytics", headers=_admin(client)
    )
    assert response.status_code == 204


# ----------------------------------------------------------------- corrupt ----


def test_corrupt_payload_degrades_to_default_instead_of_500(client, db_session):
    """A layout is a presentation preference, so a corrupt row must not take
    a dashboard down for every user."""
    from app.models.dashboard_layout import DashboardLayout

    db_session.add(
        DashboardLayout(name="admin_overview", payload="{not json at all", updated_by=None)
    )
    db_session.commit()

    response = client.get(
        "/api/v1/dashboard-layout/admin_overview", headers=_admin(client)
    )
    assert response.status_code == 200
    assert response.json()["widgets"] == {}
