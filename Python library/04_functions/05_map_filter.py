"""
Topic: map and filter
Goal: Apply functions to collections
Level: Beginner → Intermediate
"""

numbers = [1, 2, 3, 4, 5]

# map: transform each element
squared = list(map(lambda x: x**2, numbers))
print(squared)
# Output: [1, 4, 9, 16, 25]


# filter: keep elements that match condition
evens = list(filter(lambda x: x % 2 == 0, numbers))
print(evens)
# Output: [2, 4]


# Equivalent with list comprehension
squared2 = [x**2 for x in numbers]
evens2 = [x for x in numbers if x % 2 == 0]

print(squared2)
print(evens2)


# Recommendation:
# Prefer list comprehensions for readability