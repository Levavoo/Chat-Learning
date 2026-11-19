"""
Reference solutions
"""

# 1
try:
    num = int(input("Enter number: "))
    print(num)
except ValueError:
    print("Invalid input")


# 2
def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return "Cannot divide by zero"


# 3
try:
    x = int("hello")
    y = 10 / 0
except ValueError:
    print("Value error")
except ZeroDivisionError:
    print("Division error")


# 4
try:
    x = int("5")
except ValueError:
    print("Error")
else:
    print("Success")
finally:
    print("done")


# 5
def check(n):
    if n < 0:
        raise ValueError("Negative")
    return n


# 6
class PasswordError(Exception):
    pass


def validate(password):
    if len(password) < 6:
        raise PasswordError("Too short")