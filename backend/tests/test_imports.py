1import csv as _csv
import io as _io
from unittest.mock import patch

PREDICTION_RESULT = {
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


def _register_admin_and_login(client, email="importadmin@asiatech.edu.ph"):
    # Public registration was removed; users are created directly in the DB.
    client.make_user(email, role="administrator", full_name="Import Admin")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


def _register_student_and_login(client, email="importstudent@asiatech.edu.ph"):
    client.make_user(email, role="student", full_name="Import Student")
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "SecurePass123"})
    return login.json()["access_token"]


@patch("app.api.imports.process_imported_evaluations")
def test_import_requires_admin(mock_process, client, tmp_path):
    token = _register_student_and_login(client)
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text("category,comment\nFaculty,Great teaching\n")

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 403


@patch("app.api.imports.process_imported_evaluations")
def test_import_rejects_unsupported_extension(mock_process, client, tmp_path):
    token = _register_admin_and_login(client)
    txt_path = tmp_path / "feedback.txt"
    txt_path.write_text("category,comment\nFaculty,Great\n")

    with open(txt_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.txt", f, "text/plain")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 400


@patch("app.api.imports.process_imported_evaluations")
def test_import_valid_csv(mock_process, client, tmp_path):
    mock_process.return_value = type(
        "R",
        (),
        {
            "total_rows": 2,
            "imported": 2,
            "failed": 0,
            "errors": [],
        },
    )()
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "feedback.csv"
    csv_path.write_text(
        "Respondent_ID,Course,Share your thoughts\n"
        "2019-0001,BS IT,The professor explains well.\n"
        "2019-0002,BS IT,The professor is very approachable.\n"
    )

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("feedback.csv", f, "text/csv")},
            data={"category": "Faculty"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["imported"] == 2
    assert data["failed"] == 0


COMBINED_CSV = (
    "Respondent_ID,Course,"
    "Staff_Safety,Staff_Comments,"
    "Professor_TeachingQuality,Professor_Comments,"
    "Facilities_Cleanliness,Facilities_Comments,"
    "Payments_Queues,Payments_Comments\n"
    "2019-0001,BS IT,5,Staff were friendly.,4,Very clear teaching.,3,Clean rooms.,2,Long queues.\n"
)


@patch("app.api.imports.process_imported_evaluations")
def test_import_combined_csv_auto_detected(mock_process, client, tmp_path):
    """A combined multi-category file expands one row to four evaluations
    without needing the ``category`` form field."""
    captured = {}

    def fake_process(db, clean_rows, run_prediction=True, **kwargs):
        captured["clean_rows"] = clean_rows
        return type("R", (), {"total_rows": len(clean_rows), "imported": len(clean_rows), "failed": 0, "errors": []})()

    mock_process.side_effect = fake_process
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "combined.csv"
    csv_path.write_text(COMBINED_CSV)

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("combined.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["imported"] == 4
    assert data["failed"] == 0

    rows = captured["clean_rows"]
    assert sorted(r["category"] for r in rows) == [
        "Facilities", "Faculty", "Payment", "Staff",
    ]
    for r in rows:
        assert r["student_id"] == "2019-0001"
        assert r["course"] == "BS IT"
        assert r["share_your_thoughts"]
        assert r["ratings"]
    faculty = next(r for r in rows if r["category"] == "Faculty")
    assert faculty["ratings"] == {"teaching_quality": 4}



@patch("app.api.imports.process_imported_evaluations")
def test_import_empty_file_rejected(mock_process, client, tmp_path):
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("category,comment\n")

    with open(csv_path, "rb") as f:
        response = client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("empty.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Regression: a real Google Forms "Responses" export.
#
# The consolidated Ceite evaluation form exports every rating column as its
# category prefix followed by the ORIGINAL question text (not a short aspect
# name). The combined importer must resolve those full-question headers onto
# the same aspect keys the live form writes to Evaluation.ratings, otherwise
# every row is rejected with "Row has no feedback in any category".
# ---------------------------------------------------------------------------

GOOGLE_FORM_HEADERS = [
    "Timestamp",
    "Course",
    "Professor_The professors deliver lessons with good teaching quality",
    "Professor_The professors demonstrate mastery of the subject matter.",
    "Professor_The professors communicate and explain lessons clearly.",
    "Professor_The professors grade and evaluate students fairly.",
    "Professor_Rate the professors punctuality and attendance",
    "Professor_Rate the professors approachability and willingness to help students",
    "Professor_The professors  provide timely and constructive feedback on students performance.",
    "Professor_Rate the professors classroom management",
    "Professor_The professors teaching style are effective this semester.",
    "Professor_Share your thoughts",
    "Staff_The guards make me feel safe and greet me warmly whenever I enter the campus",
    "Staff_The registrar\u2019s office staff are patient and helpful when answering questions "
    "about anything that concerns documents, records and enrollment",
    "Staff_Transactions at the cashier or accounting window are stress-free and handled "
    "with great professionalism.",
    "Staff_The canteen staff serve us warmly and keep the food service area clean and organized.",
    "Staff_Substitutes and temporary staff are well-prepared and keep our regular routines "
    "going smoothly.",
    "Staff_The office staff quickly replies whenever I ask for help or need paperwork done",
    "Staff_The school administration keeps us well updated on everything through social media "
    "about campus announcement and events.",
    "Staff_The maintenance and hallway staff do a wonderful job keeping our school "
    "surroundings safe and clean.",
    "Staff_Share your thoughts",
    "Facilities_The school has great spaces like hanging spots, benches, and trees.",
    "Facilities_The classroom tables and chairs are all in good condition.",
    "Facilities_General cleanliness in all facilities are observed.",
    "Facilities_The bathrooms are always clean and smell fresh.",
    "Facilities_The cafeteria or canteen has a clean dining space with plenty of room "
    "to sit and eat.",
    "Facilities_The monitor systems in the classrooms are all well-working.",
    "Facilities_The lab computers are all easy to use and are well-managed.",
    "Facilities_The classrooms are always bright, clean and well-maintained and makes me "
    "comfortable to work properly.",
    "Facilities_Share your thoughts",
    "Payments_The payment portal/counter is easily accessible at convenient times for my schedule.",
    "Payments_My payments or fee clearances are processed and posted to my account in a "
    "timely manner.",
    "Payments_The on-site payment queues move quickly and efficiently, even during peak days.",
    "Payments_Payment personnel are courteous, helpful, and prompt in addressing "
    "payment-related inquiries or concerns.",
    "Payments_Accounting and registrar personnel are helpful, polite, and responsive when "
    "addressing payment and document-related inquiries or issues.",
    "Payments_I feel confident that my personal and financial information is secure when "
    "making transactions.",
    "Payments_The payments process provides clear and accurate information about my fees, "
    "balances, and transactions.",
    "Payments_I trust that my personal and financial information is protected when using the "
    "digital bank information system for transactions.",
    "Payments_Share your thoughts",
]

EXPECTED_ASPECTS = {
    "Faculty": [
        "teaching_quality", "mastery", "clarity", "fairness", "punctuality",
        "approachability", "feedback", "classroom_mgmt", "teaching_style",
    ],
    "Staff": [
        "safety", "registrar", "cashier", "canteen", "substitute",
        "office_staff", "admin_comm", "maintenance",
    ],
    "Facilities": [
        "spaces", "furniture", "cleanliness", "bathrooms", "cafeteria",
        "monitors", "computers", "classrooms",
    ],
    "Payment": [
        "accessibility", "processing", "queues", "courteous",
        "accounting", "security", "info_clarity", "digital_trust",
    ],
}



def _google_form_combined_csv(comment="A genuine open-ended comment."):
    """One-row combined CSV using the real Google Forms header text."""
    values = {"Timestamp": "8/25/2026 18:15:32", "Course": "BSCS"}
    for header in GOOGLE_FORM_HEADERS:
        if header in values:
            continue
        values[header] = comment if header.endswith("Share your thoughts") else "4"

    buffer = _io.StringIO()
    writer = _csv.writer(buffer)
    writer.writerow(GOOGLE_FORM_HEADERS)
    writer.writerow([values[h] for h in GOOGLE_FORM_HEADERS])
    return buffer.getvalue()


def _capture_process(captured):
    """A stand-in for process_imported_evaluations that records its input."""
    def _fake(db, clean_rows, run_prediction=True, **kwargs):
        captured["clean_rows"] = clean_rows
        return type(
            "R", (),
            {
                "total_rows": len(clean_rows),
                "imported": len(clean_rows),
                "failed": 0,
                "errors": [],
            },
        )()

    return _fake


def _post_google_form_csv(client, tmp_path, comment):
    token = _register_admin_and_login(client)
    csv_path = tmp_path / "google_form.csv"
    csv_path.write_text(_google_form_combined_csv(comment), encoding="utf-8")

    with open(csv_path, "rb") as f:
        return client.post(
            "/api/v1/imports/evaluations",
            files={"file": ("google_form.csv", f, "text/csv")},
            headers={"Authorization": f"Bearer {token}"},
        )


@patch("app.api.imports.process_imported_evaluations")
def test_import_google_forms_full_question_headers(mock_process, client, tmp_path):
    """Full-question Google Forms headers resolve to the live aspect keys."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_google_form_csv(client, tmp_path, "A genuine open-ended comment.")

    assert response.status_code == 201
    data = response.json()
    assert data["failed"] == 0
    assert data["imported"] == 4

    rows = {r["category"]: r for r in captured["clean_rows"]}
    assert set(rows) == set(EXPECTED_ASPECTS)
    for category, aspects in EXPECTED_ASPECTS.items():
        row = rows[category]
        assert row["ratings"] == {aspect: 4 for aspect in aspects}, category
        assert row["share_your_thoughts"] == "A genuine open-ended comment."
        assert row["course"] == "BSCS"


@patch("app.api.imports.process_imported_evaluations")
def test_import_google_forms_placeholder_comment_kept_as_ratings(
    mock_process, client, tmp_path
):
    """A 1-2 char placeholder ("NA") must not drop a fully-rated record."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_google_form_csv(client, tmp_path, "NA")

    assert response.status_code == 201
    data = response.json()
    assert data["failed"] == 0
    assert data["imported"] == 4

    for row in captured["clean_rows"]:
        assert row["share_your_thoughts"] is None
        assert len(row["ratings"]) == len(EXPECTED_ASPECTS[row["category"]])


# ---------------------------------------------------------------------------
# Regression: single-category Faculty / Payment files.
#
# The admin UI's import dropdown sends "Faculty" / "Payment"; the API enum
# stores "Professors" / "Payments" (FastAPI coerces the form value through its
# aliases before the service runs); the per-category keyword tables in
# import_service are keyed on "Faculty" / "Payment". Before the alias fold-in,
# a single-category Faculty/Payment file imported as a comment-only evaluation
# (every rating question unresolved, evaluatee dropped by the
# `category != "Faculty"` rule) and a file whose own Category column said
# "Faculty" had all of its rows rejected as a category mismatch.
# ---------------------------------------------------------------------------

SINGLE_FACULTY_CSV = (
    "Timestamp,Course,Professor Name,"
    "The professors demonstrate mastery of the subject matter.,"
    "Share your thoughts\n"
    "8/25/2026,BSCS,Prof. Cruz,5,Great teacher.\n"
)


def _post_single(client, tmp_path, csv_text, category, filename="single.csv"):
    token = _register_admin_and_login(client)
    csv_path = tmp_path / filename
    csv_path.write_text(csv_text, encoding="utf-8")

    with open(csv_path, "rb") as f:
        return client.post(
            "/api/v1/imports/evaluations",
            files={"file": (filename, f, "text/csv")},
            data={"category": category},
            headers={"Authorization": f"Bearer {token}"},
        )


@patch("app.api.imports.process_imported_evaluations")
def test_import_single_faculty_keeps_ratings_evaluatee_and_course(
    mock_process, client, tmp_path
):
    """Selecting the Professor/Faculty form must keep the Likert ratings, the
    professor column and the row's Course — not fall back to a comment-only
    evaluation."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_single(client, tmp_path, SINGLE_FACULTY_CSV, "Faculty")

    assert response.status_code == 201
    assert response.json()["failed"] == 0

    row = captured["clean_rows"][0]
    assert row["category"] == "Faculty"
    assert row["course"] == "BSCS"
    assert row["evaluatee"] == "Prof. Cruz"
    assert row["ratings"] == {"mastery": 5}


@patch("app.api.imports.process_imported_evaluations")
def test_import_single_faculty_rating_question_is_not_the_evaluatee(
    mock_process, client, tmp_path
):
    """A rating question that mentions "professor" must never be mistaken for
    the professor-name column, even when it comes first in the header row."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_single(
        client,
        tmp_path,
        "Timestamp,Course,"
        "The professors demonstrate mastery of the subject matter.,"
        "Professor Name,Share your thoughts\n"
        "8/25/2026,BSCS,5,Prof. Cruz,Great teacher.\n",
        "Faculty",
    )

    assert response.status_code == 201
    row = captured["clean_rows"][0]
    assert row["evaluatee"] == "Prof. Cruz"
    assert row["ratings"] == {"mastery": 5}
    assert row["course"] == "BSCS"


@patch("app.api.imports.process_imported_evaluations")
def test_import_single_course_column_is_not_claimed_as_evaluatee(
    mock_process, client, tmp_path
):
    """A lone 'Course' column must never be reused as the evaluatee column —
    otherwise the course value is rendered as the professor's name."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_single(
        client,
        tmp_path,
        "Timestamp,Course,Share your thoughts\n"
        "8/25/2026,BSCS,Great teacher.\n",
        "Faculty",
    )

    assert response.status_code == 201
    row = captured["clean_rows"][0]
    assert row["course"] == "BSCS"
    assert row["evaluatee"] is None


@patch("app.api.imports.process_imported_evaluations")
def test_import_single_payment_alias_resolves_ratings(mock_process, client, tmp_path):
    """'Payment' (the UI spelling) resolves the Payment rating questions and
    keeps the row's Course."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_single(
        client,
        tmp_path,
        "Timestamp,Course,The payment portal is easily accessible,Share your thoughts\n"
        "8/25/2026,BSCS,5,Quick and easy.\n",
        "Payment",
    )

    assert response.status_code == 201
    row = captured["clean_rows"][0]
    assert row["category"] == "Payment"
    assert row["course"] == "BSCS"
    assert row["ratings"] == {"accessibility": 5}


@patch("app.api.imports.process_imported_evaluations")
def test_import_single_category_column_alias_matches_selection(
    mock_process, client, tmp_path
):
    """A file whose Category column says 'Faculty' is imported cleanly when the
    admin picks the Faculty form — no bogus per-row mismatch."""
    captured = {}
    mock_process.side_effect = _capture_process(captured)

    response = _post_single(
        client,
        tmp_path,
        "Timestamp,Course,Category,Share your thoughts\n"
        "8/25/2026,BSCS,Faculty,Great teacher.\n",
        "Faculty",
    )

    assert response.status_code == 201
    assert response.json()["failed"] == 0

    row = captured["clean_rows"][0]
    assert row["category"] == "Faculty"
    assert row["course"] == "BSCS"

