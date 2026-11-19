"""
Topic: CSV
Goal: Work with tabular data
Level: Beginner
"""

import csv

# Write CSV
with open("data.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["name", "age"])
    writer.writerow(["Alice", 25])
    writer.writerow(["Bob", 30])

# Read CSV
with open("data.csv", "r") as f:
    reader = csv.reader(f)
    for row in reader:
        print(row)

# Output:
# ['name', 'age']
# ['Alice', '25']
# ['Bob', '30']

# Using DictReader
with open("data.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        print(row["name"], row["age"])