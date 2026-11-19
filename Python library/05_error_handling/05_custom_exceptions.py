"""
Topic: Custom Exceptions
Goal: Create your own error types
Level: Intermediate
"""

class CustomError(Exception):
    pass


def check_value(x):
    if x < 0:
        raise CustomError("Negative value not allowed")


try:
    check_value(-5)
except CustomError as e:
    print("Custom error:", e)

# Output: Custom error: Negative value not allowed


# More meaningful example
class InsufficientFundsError(Exception):
    pass


def withdraw(balance, amount):
    if amount > balance:
        raise InsufficientFundsError("Not enough money")
    return balance - amount


try:
    withdraw(100, 200)
except InsufficientFundsError as e:
    print(e)