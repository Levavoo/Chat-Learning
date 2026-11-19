"""
Topic: Unpacking
Goal: Use * and ** operators
"""

# List unpacking
nums = [1, 2, 3]
a, b, c = nums

# Extended unpacking
a, *rest = [1, 2, 3, 4]
print(a, rest)  # 1 [2,3,4]

# Function unpacking
def add(a, b, c):
    return a + b + c

values = [1, 2, 3]
print(add(*values))

# Dict unpacking
d = {"a": 1, "b": 2}
def show(a, b):
    print(a, b)

show(**d)

# Merge dicts
d1 = {"x": 1}
d2 = {"y": 2}
merged = {**d1, **d2}
print(merged)