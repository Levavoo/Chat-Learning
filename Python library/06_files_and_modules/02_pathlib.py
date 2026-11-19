"""
Topic: pathlib
Goal: Work with file paths safely
Level: Beginner → Intermediate
"""

from pathlib import Path

# Create path object
path = Path("example.txt")

# Check existence
print(path.exists())

# File info
print(path.name)
print(path.suffix)

# Read file
if path.exists():
    print(path.read_text())

# Write file
path.write_text("New content")

# Create directory
folder = Path("data")
folder.mkdir(exist_ok=True)

# Join paths
file_path = folder / "file.txt"
file_path.write_text("Hello")

# Pitfall: avoid manual string paths