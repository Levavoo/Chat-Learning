"""
Topic: if / elif / else
Goal: Control program flow with conditions
Level: Beginner
"""

age = 20

if age < 18:
    print("Minor")
elif age == 18:
    print("Just adult")
else:
    print("Adult")

# Output: Adult

# Multiple conditions
temperature = 30

if temperature > 35:
    print("Very hot")
elif temperature > 25:
    print("Warm")
else:
    print("Cool")

# Output: Warm

# Using logical operators
has_ticket = True
has_id = True

if has_ticket and has_id:
    print("Access granted")
else:
    print("Access denied")

# Output: Access granted

# Nested conditions
score = 85

if score >= 50:
    if score >= 80:
        print("Excellent")
    else:
        print("Passed")
else:
    print("Failed")

# Output: Excellent

# Pitfall: indentation matters
# Wrong:
# if age > 18:
# print("Adult")  # Error