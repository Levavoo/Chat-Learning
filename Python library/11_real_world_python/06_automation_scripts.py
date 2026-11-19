"""
Topic: Automation Scripts
Goal: Automate tasks
"""

import os

# List files
files = os.listdir(".")

for f in files:
    print(f)

# Rename example
for f in files:
    if f.endswith(".txt"):
        new_name = f"new_{f}"
        os.rename(f, new_name)

# Warning: be careful with file operations