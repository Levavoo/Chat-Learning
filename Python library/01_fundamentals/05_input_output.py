"""
Topic: Input and Output
Goal: Learn how to print values and read user input
Level: Beginner
"""

# Basic output
print("Hello, Python")
# Output: Hello, Python

name = "Lina"
age = 28

print(name)
print(age)

# Printing multiple values
print("Name:", name, "| Age:", age)
# Output: Name: Lina | Age: 28

# f-string output
print(f"{name} is {age} years old.")
# Output: Lina is 28 years old.

# Input always returns a string
user_name = input("Enter your name: ")
print(f"Hello, {user_name}!")

# Example interaction:
# Enter your name: Alex
# Hello, Alex!

user_age = input("Enter your age: ")
print(type(user_age))
# Output: <class 'str'>

# Pitfall:
# next year this will fail if user_age is still a string
# print(user_age + 1)

# Correct version:
user_age = int(user_age)
print(f"Next year you will be {user_age + 1}.")