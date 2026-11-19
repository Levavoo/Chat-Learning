"""
Topic: Variables and Types
Goal: Learn how to store values and inspect their types
Level: Beginner
"""

# Variables store values
name = "Alice"
age = 25
height = 1.72
is_student = True

print(name)
print(age)
print(height)
print(is_student)

# Output:
# Alice
# 25
# 1.72
# True

# Python has dynamic typing
# You do not need to declare the type manually
city = "Berlin"
print(type(city))       # Output: <class 'str'>
print(type(age))        # Output: <class 'int'>
print(type(height))     # Output: <class 'float'>
print(type(is_student)) # Output: <class 'bool'>

# Variable names should be descriptive
favorite_food = "Pizza"
print(favorite_food)

# Bad style:
x = 10
# Better:
user_age = 10

# Variables can be changed
score = 5
print(score)  # Output: 5

score = 8
print(score)  # Output: 8

# Pitfall: overwriting a variable with a different type
value = 100
print(type(value))  # Output: <class 'int'>

value = "100"
print(type(value))  # Output: <class 'str'>

# This is allowed, but can become confusing in bigger programs