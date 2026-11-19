"""
Topic: List Comprehensions
Goal: Create lists in a compact way
Level: Beginner → Intermediate
"""

# Basic example
numbers = [1, 2, 3, 4]

squared = [x**2 for x in numbers]
print(squared)
# Output: [1, 4, 9, 16]

# With condition
even_numbers = [x for x in numbers if x % 2 == 0]
print(even_numbers)
# Output: [2, 4]

# With transformation
labels = ["even" if x % 2 == 0 else "odd" for x in numbers]
print(labels)
# Output: ['odd', 'even', 'odd', 'even']

# Nested loop
pairs = [(x, y) for x in [1, 2] for y in [3, 4]]
print(pairs)
# Output: [(1, 3), (1, 4), (2, 3), (2, 4)]

# Equivalent normal loop
result = []
for x in numbers:
    result.append(x**2)

# Pitfall: readability
# Avoid very complex comprehensions