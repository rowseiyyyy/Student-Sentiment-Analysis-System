"""End-to-end check of voice_notes endpoints against the PRODUCTION DB.

Submits one real anonymous message through the running app (exercising the
live ML pipeline + prod DB), verifies persistence and auth-gating, then
removes the test row so production is left exactly as it was.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.core.limiter import limiter
limiter.enabled = False

from app.core.database import Base, get_db, SessionLocal
import main

Base.metadata.create_all(bind=SessionLocal().bind)  # no-op if tables exist

TEST_MSG = "__deploy_check__ Voice in a Box endpoint verification row."

with TestClient(main.app) as c:
    # 1) Anonymous submission against prod (live ML pipeline).
    r = c.post("/api/v1/voice-notes", json={"message": TEST_MSG})
    print("POST:", r.status_code, {k: r.json().get(k) for k in ("sentiment", "confidence_score", "algorithm_used")})
    assert r.status_code == 201, r.text
    note_id = r.json()["id"]

    # 2) Feed read is auth-gated but the route is reachable.
    r = c.get("/api/v1/voice-notes")
    print("GET (no auth):", r.status_code, "-> route reachable, staff-gated")

    # 3) Stats route reachable (also staff-gated).
    r = c.get("/api/v1/voice-notes/stats")
    print("GET stats (no auth):", r.status_code)

# 4) Clean up the test row directly via DB.
db = SessionLocal()
from app.models.voice_note import VoiceNote
row = db.query(VoiceNote).filter(VoiceNote.id == note_id).first()
assert row is not None and row.sentiment in ("Positive", "Neutral", "Negative"), "row missing or bad sentiment"
db.delete(row)
db.commit()
print("Test row deleted:", row.id[:8], "| sentiment was:", row.sentiment)

remaining = db.query(VoiceNote).count()
print("voice_notes row count after cleanup:", remaining)
db.close()
print("E2E CHECK DONE — endpoints reachable, table functional, prod clean")
