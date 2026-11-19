"""
Topic: Tuples
Goal: Store ordered, immutable data
Level: Beginner
"""

point = (10, 20)

print(point)
# Output: (10, 20)

# Access
print(point[0])  # 10

# Tuple unpacking
x, y = point
print(x, y)

# Output: 10 20

# Single element tuple
single = (5,)
print(type(single))  # tuple

# Tuple without parentheses
a, b = 1, 2
print(a, b)

# Pitfall: immutability
# point[0] = 5  # Error

# Use case: fixed data
user = ("Alice", 25)