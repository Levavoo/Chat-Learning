"""
Topic: Specific Exceptions
Goal: Handle different errors properly
Level: Beginner
"""

try:
    num = int("hello")
except ValueError:
    print("Invalid number")

# Output: Invalid number


# Multiple exceptions
try:
    result = 10 / 0
except ZeroDivisionError:
    print("Cannot divide by zero")
except ValueError:
    print("Wrong value")

# Output: Cannot divide by zero


# Catch exception object
try:
    x = int("abc")
except ValueError as e:
    print("Error:", e)