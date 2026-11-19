"""
Topic: Function Basics
Goal: Define and use functions
Level: Beginner
"""

# Define function
def greet():
    print("Hello")

greet()
# Output: Hello


# Function with parameters
def greet_user(name):
    print(f"Hello, {name}")

greet_user("Alice")
# Output: Hello, Alice


# Return value
def add(a, b):
    return a + b

result = add(3, 5)
print(result)
# Output: 8


# Difference between print and return
def wrong_add(a, b):
    print(a + b)

x = wrong_add(2, 3)
print(x)
# Output:
# 5
# None


# Multiple returns
def check_number(n):
    if n > 0:
        return "positive"
    elif n < 0:
        return "negative"
    return "zero"

print(check_number(-2))
# Output: negative