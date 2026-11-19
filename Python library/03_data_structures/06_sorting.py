"""
Topic: Sorting
Goal: Sort lists and complex data
Level: Beginner → Intermediate
"""

numbers = [5, 2, 9, 1]

# sorted (new list)
sorted_numbers = sorted(numbers)
print(sorted_numbers)

# reverse
print(sorted(numbers, reverse=True))

# in-place sort
numbers.sort()
print(numbers)

# Sorting strings
words = ["banana", "apple", "cherry"]
print(sorted(words))

# Sorting with key
data = [
    {"name": "Alice", "age": 25},
    {"name": "Bob", "age": 20}
]

sorted_data = sorted(data, key=lambda x: x["age"])
print(sorted_data)

# Output:
# [{'name': 'Bob', 'age': 20}, {'name': 'Alice', 'age': 25}]

# Pitfall: sort modifies list, sorted does not