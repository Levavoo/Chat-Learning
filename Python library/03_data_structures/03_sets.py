"""
Topic: Sets
Goal: Store unique unordered elements
Level: Beginner
"""

numbers = {1, 2, 3, 3, 4}
print(numbers)
# Output: {1, 2, 3, 4}

# Add/remove
numbers.add(5)
numbers.remove(2)

print(numbers)

# Membership test
print(3 in numbers)  # True

# Set operations
a = {1, 2, 3}
b = {3, 4, 5}

print(a | b)  # union: {1,2,3,4,5}
print(a & b)  # intersection: {3}
print(a - b)  # difference: {1,2}

# Loop
for n in numbers:
    print(n)

# Pitfall: no indexing
# numbers[0]  # Error