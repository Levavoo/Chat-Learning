"""
Topic: SQLite
Goal: Store data in database
"""

import sqlite3

conn = sqlite3.connect("example.db")
cursor = conn.cursor()

# Create table
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER
)
""")

# Insert
cursor.execute("INSERT INTO users (name, age) VALUES (?, ?)", ("Alice", 25))

# Query
cursor.execute("SELECT * FROM users")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.commit()
conn.close()