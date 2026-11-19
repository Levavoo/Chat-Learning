"""
Topic: else and finally
Goal: Understand full try-except flow
Level: Beginner
"""

try:
    x = int("5")
except ValueError:
    print("Error")
else:
    print("Success:", x)
finally:
    print("Always runs")

# Output:
# Success: 5
# Always runs


# File example
try:
    file = open("test.txt")
except FileNotFoundError:
    print("File not found")
finally:
    print("Closing attempt done")