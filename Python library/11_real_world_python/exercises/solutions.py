"""
Reference solutions
"""

# 2 API
import requests
data = requests.get("https://jsonplaceholder.typicode.com/todos/1").json()
print(data)


# 3 API processing
users = requests.get("https://jsonplaceholder.typicode.com/users").json()
for u in users:
    print(u["email"])


# 5 SQLite
import sqlite3

conn = sqlite3.connect("test.db")
cur = conn.cursor()

cur.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER, name TEXT)")
cur.execute("INSERT INTO test VALUES (1, 'A')")
cur.execute("SELECT * FROM test")

print(cur.fetchall())
conn.close()