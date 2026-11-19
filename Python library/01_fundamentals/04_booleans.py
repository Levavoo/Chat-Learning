"""
Topic: Booleans
Goal: Understand True, False, comparisons, and logical operators
Level: Beginner
"""

is_active = True
is_admin = False

print(is_active)  # Output: True
print(is_admin)   # Output: False

# Comparison operators
print(5 > 3)    # Output: True
print(5 < 3)    # Output: False
print(5 == 5)   # Output: True
print(5 != 5)   # Output: False
print(5 >= 5)   # Output: True
print(5 <= 4)   # Output: False

# Logical operators
age = 20
has_ticket = True

print(age >= 18 and has_ticket)  # Output: True
print(age >= 18 or has_ticket)   # Output: True
print(not has_ticket)            # Output: False

# Truthy and falsy values
print(bool(0))        # Output: False
print(bool(1))        # Output: True
print(bool(""))       # Output: False
print(bool("text"))   # Output: True
print(bool([]))       # Output: False
print(bool([1, 2]))   # Output: True

# Pitfall: = is assignment, == is comparison
number = 5
print(number == 5)  # Output: True