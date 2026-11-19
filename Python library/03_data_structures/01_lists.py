"""
Topic: Lists
Goal: Store ordered, mutable collections
Level: Beginner
"""

numbers = [1, 2, 3, 4]

print(numbers)
# Output: [1, 2, 3, 4]

# Indexing
print(numbers[0])   # 1
print(numbers[-1])  # 4

# Modify element
numbers[1] = 10
print(numbers)  # [1, 10, 3, 4]

# Add elements
numbers.append(5)
print(numbers)  # [1, 10, 3, 4, 5]

numbers.insert(1, 99)
print(numbers)  # [1, 99, 10, 3, 4, 5]

# Remove elements
numbers.remove(10)
print(numbers)

last = numbers.pop()
print(last)
print(numbers)

# Slicing
print(numbers[1:4])

# Length
print(len(numbers))

# Loop
for num in numbers:
    print(num)

# Pitfall: copying lists
a = [1, 2, 3]
b = a  # reference, not copy

b.append(4)
print(a)  # [1, 2, 3, 4]

# Correct copy
c = a.copy()
c.append(5)
print(a)  # unchanged