"""Inspect production DB state for voice_notes (READ-ONLY — changes nothing)."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
insp = inspect(engine)

with engine.connect() as conn:
    print("=== alembic_version ===")
    if insp.has_table("alembic_version"):
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        print("version rows:", rows)
    else:
        print("no alembic_version table!")

    print("\n=== table existence ===")
    print("voice_notes exists:", insp.has_table("voice_notes"))

    if insp.has_table("voice_notes"):
        print("\n=== SHOW CREATE TABLE voice_notes ===")
        ddl = conn.execute(text("SHOW CREATE TABLE voice_notes")).fetchone()
        print(ddl[1])

        print("\n=== actual columns ===")
        for c in insp.get_columns("voice_notes"):
            print(f"  {c['name']}: {c['type']} nullable={c.get('nullable')}")

        print("\n=== indexes ===")
        for i in insp.get_indexes("voice_notes"):
            print(f"  {i['name']}: cols={i['column_names']} unique={i['unique']}")

        print("\n=== row count ===")
        count = conn.execute(text("SELECT COUNT(*) FROM voice_notes")).scalar()
        print("rows:", count)

        if count:
            print("\n=== all rows (id, created_at, sentiment, conf, msg len) ===")
            rows = conn.execute(text(
                "SELECT id, created_at, sentiment, confidence_score, algorithm_used, "
                "CHAR_LENGTH(message) AS msg_len, processing_time_ms FROM voice_notes "
                "ORDER BY created_at"
            )).fetchall()
            for r in rows:
                print(" ", r)

            print("\n=== data-quality checks ===")
            nulls = conn.execute(text(
                "SELECT COUNT(*) FROM voice_notes WHERE sentiment IS NULL OR confidence_score IS NULL"
            )).scalar()
            print("rows with NULL sentiment/confidence:", nulls)
            dups = conn.execute(text(
                "SELECT COUNT(*) FROM (SELECT message, COUNT(*) c FROM voice_notes "
                "GROUP BY message HAVING c > 1) d"
            )).scalar()
            print("duplicate messages:", dups)
            blank = conn.execute(text(
                "SELECT COUNT(*) FROM voice_notes WHERE TRIM(message) = ''"
            )).scalar()
            print("blank messages:", blank)

engine.dispose()
print("\nINSPECTION DONE (no changes made)")
