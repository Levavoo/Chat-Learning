"""
Topic: match-case
Goal: Pattern matching (Python 3.10+)
Level: Beginner
"""

day = "Monday"

match day:
    case "Monday":
        print("Start of the week")
    case "Friday":
        print("Almost weekend")
    case "Saturday" | "Sunday":
        print("Weekend")
    case _:
        print("Regular day")

# Output: Start of the week

# Matching numbers
status_code = 404

match status_code:
    case 200:
        print("OK")
    case 404:
        print("Not Found")
    case 500:
        print("Server Error")
    case _:
        print("Unknown")

# Output: Not Found

# Pitfall:
# match is not just switch — it supports patterns (advanced later)