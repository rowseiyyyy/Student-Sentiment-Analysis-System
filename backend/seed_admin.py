"""Seed default admin/faculty users with known passwords."""
import sys
sys.path.insert(0, '.')

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.models.evaluation import Evaluation
from app.models.prediction import Prediction
from app.models.training_history import TrainingHistory
import uuid

db = SessionLocal()

# Check if admin exists
admin = db.query(User).filter(User.email == "admin@asiatech.edu.ph").first()
if admin:
    # Reset password
    admin.hashed_password = hash_password("AdminPass123")
    print(f"Updated admin password: {admin.email}")
else:
    admin = User(
        id=str(uuid.uuid4()),
        full_name="System Administrator",
        email="admin@asiatech.edu.ph",
        hashed_password=hash_password("AdminPass123"),
        role=UserRole.ADMINISTRATOR,
        is_active=True
    )
    db.add(admin)
    print(f"Created admin: {admin.email} / AdminPass123")

# Also check/faculty
faculty = db.query(User).filter(User.email == "faculty@asiatech.edu.ph").first()
if not faculty:
    faculty = User(
        id=str(uuid.uuid4()),
        full_name="Faculty Member",
        email="faculty@asiatech.edu.ph",
        hashed_password=hash_password("FacultyPass123"),
        role=UserRole.FACULTY,
        is_active=True
    )
    db.add(faculty)
    print(f"Created faculty: {faculty.email} / FacultyPass123")

db.commit()
db.close()

print("\nSeed complete! Test credentials:")
print("  Admin: admin@asiatech.edu.ph / AdminPass123")
print("  Faculty: faculty@asiatech.edu.ph / FacultyPass123")
print("  Faculty (existing): faculty-test@example.com / password123")
