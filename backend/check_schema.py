import sqlite3

conn = sqlite3.connect("asiatech_sentiment.db")
cols = [row[1] for row in conn.execute("PRAGMA table_info(evaluations)")]
print(cols)
conn.close()