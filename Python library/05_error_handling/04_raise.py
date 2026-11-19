"""
Topic: raise
Goal: Trigger errors manually
Level: Beginner → Intermediate
"""

def divide(a, b):
    if b == 0:
        raise ValueError("b cannot be zero")
    return a / b

# print(divide(10, 0))  # raises error


# Custom validation
def set_age(age):
    if age < 0:
        raise ValueError("Age cannot be negative")
    return age


# Using raise in logic
def withdraw(balance, amount):
    if amount > balance:
        raise ValueError("Insufficient funds")
    return balance - amount