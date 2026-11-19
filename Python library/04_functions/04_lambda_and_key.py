"""
Topic: Lambda and Key Functions
Goal: Use lambda functions and key for sorting and transformations
Level: Beginner → Intermediate
"""

# Basic lambda
add = lambda a, b: a + b
print(add(2, 3))
# Output: 5


# Equivalent function
def add_func(a, b):
    return a + b


# Lambda with one input
square = lambda x: x**2
print(square(4))
# Output: 16


# Using lambda with sorted
data = [
    {"name": "Alice", "age": 25},
    {"name": "Bob", "age": 20},
    {"name": "Charlie", "age": 30}
]

# Sort by age
sorted_by_age = sorted(data, key=lambda x: x["age"])
print(sorted_by_age)

# Sort by name
sorted_by_name = sorted(data, key=lambda x: x["name"])
print(sorted_by_name)


# Reverse sorting
sorted_desc = sorted(data, key=lambda x: x["age"], reverse=True)
print(sorted_desc)


# Important mental model:
# key=lambda x: x["age"]
# → take each item → extract age → sort by that


# Lambda for simple transformation
numbers = [1, 2, 3]
result = list(map(lambda x: x * 2, numbers))
print(result)
# Output: [2, 4, 6]


# Pitfall: do not overuse lambda
# Bad:
# lambda x: (x + 1 if x > 2 else x * 2 if x < 0 else x)

# Better: use a normal function