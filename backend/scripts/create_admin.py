"""
One-off script to create the first administrator account.

Run from the backend/ directory:
    python scripts/create_admin.py
"""
import sys
from pathlib import Path

_backend_dir = str(Path(__file__).resolve().parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
import app.models.evaluation  # noqa: F401
import app.models.prediction  # noqa: F401
import app.models.training_history  # noqa: F401

def main():
    email = input("Admin email: ").strip()
    full_name = input("Full name: ").strip()
    password = input("Password (min 8 chars): ").strip()

    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"A user with email {email} already exists (role={existing.role}).")
            return

        user = User(
            full_name=full_name,
            email=email,
            hashed_password=hash_password(password),
            role=UserRole.ADMINISTRATOR,
        )
        db.add(user)
        db.commit()
        print(f"Administrator account created: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()