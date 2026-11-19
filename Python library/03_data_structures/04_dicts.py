"""
Topic: Dictionaries
Goal: Store key-value pairs
Level: Beginner
"""

user = {
    "name": "Alice",
    "age": 25,
    "is_admin": False
}

print(user)

# Access
print(user["name"])  # Alice

# Safe access
print(user.get("age"))       # 25
print(user.get("email"))     # None

# Add/update
user["email"] = "alice@test.com"
user["age"] = 26

# Remove
user.pop("is_admin")

print(user)

# Keys / values
print(user.keys())
print(user.values())
print(user.items())

# Loop
for key, value in user.items():
    print(key, value)

# Pitfall: KeyError
# print(user["missing"])  # Error