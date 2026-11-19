"""
Topic: Loops
Goal: Repeat actions using for and while loops
Level: Beginner
"""

# For loop with range
for i in range(5):
    print(i)

# Output:
# 0 1 2 3 4

# Loop over list
fruits = ["apple", "banana", "orange"]

for fruit in fruits:
    print(fruit)

# Output:
# apple
# banana
# orange

# Loop over string
for char in "Python":
    print(char)

# While loop
count = 0

while count < 3:
    print(count)
    count += 1

# Output:
# 0 1 2

# Infinite loop example (DO NOT RUN)
# while True:
#     print("This never stops")

# Loop with index
numbers = [10, 20, 30]

for i in range(len(numbers)):
    print(i, numbers[i])

# Output:
# 0 10
# 1 20
# 2 30