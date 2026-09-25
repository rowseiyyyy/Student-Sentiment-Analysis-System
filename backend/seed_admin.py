"""Seed default Admin/Faculty accounts with the institution default passwords.

Accounts live on the @asiatech.edu.ph domain only — there is no public
sign-up. Students are anonymous and never have accounts.

Usage:
    cd backend && python seed_admin.py [more emails ...]

Every seeded account keeps the default password (ASIATECH-admin123 /
ASIATECH-faculty123) so the login UI can offer a change on first sign-in.
Pass extra emails as arguments to create additional accounts; the role is
derived from a naming hint or defaults to faculty.
"""
import sys
import uuid

sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.action_update import ActionUpdate
from app.models.evaluation import Evaluation
from app.models.prediction import Prediction
from app.models.training_history import TrainingHistory
from app.models.voice_note import VoiceNote
from app.models.user import User, UserRole

ALLOWED_DOMAIN = "@asiatech.edu.ph"
DEFAULT_ADMIN_PASSWORD = "ASIATECH-admin123"
DEFAULT_FACULTY_PASSWORD = "ASIATECH-faculty123"


def seed(email: str, full_name: str, role: UserRole) -> None:
    if not email.lower().endswith(ALLOWED_DOMAIN):
        print(f"SKIP {email}: only @{ALLOWED_DOMAIN} accounts can be created.")
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        default_password = (
            DEFAULT_ADMIN_PASSWORD if role == UserRole.ADMINISTRATOR else DEFAULT_FACULTY_PASSWORD
        )
        if user:
            print(f"EXISTS {email} (role={user.role.value}) — left untouched.")
            return
        db.add(
            User(
                id=str(uuid.uuid4()),
                full_name=full_name,
                email=email,
                hashed_password=hash_password(default_password),
                role=role,
                is_active=True,
            )
        )
        db.commit()
        print(f"CREATED {email} / {default_password}")
    finally:
        db.close()


if __name__ == "__main__":
    seed("admin@asiatech.edu.ph", "System Administrator", UserRole.ADMINISTRATOR)
    seed("faculty@asiatech.edu.ph", "Faculty Member", UserRole.FACULTY)

    for extra in sys.argv[1:]:
        role = UserRole.ADMINISTRATOR if "admin" in extra.lower() else UserRole.FACULTY
        seed(extra, extra.split("@")[0].replace(".", " ").title(), role)

    print("\nSeed complete. Default passwords:")
    print(f"  Admin:   {DEFAULT_ADMIN_PASSWORD}")
    print(f"  Faculty: {DEFAULT_FACULTY_PASSWORD}")

