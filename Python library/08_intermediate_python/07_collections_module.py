"""
Topic: collections module
"""

from collections import Counter, defaultdict

# Counter
data = ["a", "b", "a"]
count = Counter(data)
print(count)  # {'a':2, 'b':1}

# defaultdict
d = defaultdict(int)
d["x"] += 1
print(d)  # {'x':1}