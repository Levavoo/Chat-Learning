"""
Topic: Regex
"""

import re

text = "My number is 12345"

match = re.search(r"\d+", text)
print(match.group())  # 12345

# Find all
print(re.findall(r"\d+", text))