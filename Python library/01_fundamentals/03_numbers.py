"""
Topic: Numbers
Goal: Learn integer, float, arithmetic, and useful numeric operations
Level: Beginner
"""

a = 10
b = 3

print(a + b)   # Output: 13
print(a - b)   # Output: 7
print(a * b)   # Output: 30
print(a / b)   # Output: 3.3333333333333335
print(a // b)  # Output: 3
print(a % b)   # Output: 1
print(a ** b)  # Output: 1000

# Floats
price = 19.99
tax = 0.20
total = price + tax
print(total)   # Output: 20.189999999999998

# Rounding
print(round(total, 2))  # Output: 20.19

# Useful built-ins
numbers = [4, 8, 1, 9, 2]
print(min(numbers))  # Output: 1
print(max(numbers))  # Output: 9
print(sum(numbers))  # Output: 24

# Absolute value
print(abs(-7))  # Output: 7

# Pitfall: division always returns float
result = 4 / 2
print(result)        # Output: 2.0
print(type(result))  # Output: <class 'float'>