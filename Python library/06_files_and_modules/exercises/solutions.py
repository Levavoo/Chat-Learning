"""
Reference solutions
"""

# 1
with open("test.txt", "w") as f:
    f.write("Line 1\nLine 2\nLine 3")

with open("test.txt", "r") as f:
    print(f.read())


# 2
with open("test.txt", "a") as f:
    f.write("\nNew line")


# 3
import json

data = {"x": 1, "y": 2}

with open("data.json", "w") as f:
    json.dump(data, f)

with open("data.json", "r") as f:
    print(json.load(f))


# 4
import csv

with open("file.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["a", "b"])
    writer.writerow([1, 2])

with open("file.csv") as f:
    for row in csv.reader(f):
        print(row)


# 5
# utils.py:
# def multiply(a, b):
#     return a * b

# main file:
# from utils import multiply
# print(multiply(2, 3))


# 6
from pathlib import Path

folder = Path("my_folder")
folder.mkdir(exist_ok=True)

file = folder / "file.txt"
file.write_text("hello")

print(file.read_text())