"""
Topic: break / continue / pass
Goal: Control loop behavior
Level: Beginner
"""

# break: stop loop completely
for i in range(5):
    if i == 3:
        break
    print(i)

# Output:
# 0 1 2

# continue: skip current iteration
for i in range(5):
    if i == 2:
        continue
    print(i)

# Output:
# 0 1 3 4

# pass: placeholder (does nothing)
for i in range(3):
    if i == 1:
        pass  # do nothing
    print(i)

# Output:
# 0 1 2

# Practical example
numbers = [1, 2, 3, 4, 5]

for num in numbers:
    if num % 2 == 0:
        continue
    print(num)

# Output:
# 1 3 5