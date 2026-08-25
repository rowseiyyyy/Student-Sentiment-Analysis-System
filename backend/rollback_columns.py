import sqlite3

conn = sqlite3.connect("asiatech_sentiment.db")
conn.execute("ALTER TABLE evaluations DROP COLUMN is_mismatch")
conn.execute("ALTER TABLE evaluations DROP COLUMN mismatch_type")
conn.commit()

cols = [row[1] for row in conn.execute("PRAGMA table_info(evaluations)")]
print(cols)
conn.close()
