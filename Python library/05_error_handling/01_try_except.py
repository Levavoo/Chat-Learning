"""
Topic: try / except
Goal: Catch and handle errors
Level: Beginner
"""

# Basic example
try:
    x = int("10")
    print(x)
except:
    print("Error occurred")

# Output: 10


# Error example
try:
    x = int("hello")
    print(x)
except:
    print("Conversion failed")

# Output: Conversion failed


# Without try/except → crash
# x = int("hello")  # ValueError