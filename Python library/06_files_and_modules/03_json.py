"""
Topic: JSON
Goal: Read and write structured data
Level: Beginner
"""

import json

data = {
    "name": "Alice",
    "age": 25
}

# Write JSON
with open("data.json", "w") as f:
    json.dump(data, f, indent=4)

# Read JSON
with open("data.json", "r") as f:
    loaded = json.load(f)

print(loaded)

# Output:
# {'name': 'Alice', 'age': 25}

# Convert to string
json_str = json.dumps(data)
print(json_str)

# Convert from string
parsed = json.loads(json_str)
print(parsed)