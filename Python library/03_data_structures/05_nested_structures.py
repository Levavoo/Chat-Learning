"""
Topic: Nested Structures
Goal: Combine lists, dicts, and more
Level: Beginner → Intermediate
"""

users = [
    {"name": "Alice", "age": 25},
    {"name": "Bob", "age": 30}
]

print(users[0]["name"])  # Alice

# Loop nested
for user in users:
    print(user["name"], user["age"])

# Dict with list
data = {
    "numbers": [1, 2, 3],
    "status": True
}

print(data["numbers"][1])  # 2

# Modify nested
users[1]["age"] = 31

# Pitfall: deep vs shallow copy
import copy

original = [{"a": 1}]
shallow = original.copy()
deep = copy.deepcopy(original)

original[0]["a"] = 99

print(shallow)  # affected
print(deep)     # not affected