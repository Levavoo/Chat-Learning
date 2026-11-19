"""
Topic: Imports and Modules
Goal: Use code from other files
Level: Beginner
"""

# Assume we have file utils.py with:
# def add(a, b):
#     return a + b

# Import entire module
import utils

print(utils.add(2, 3))

# Import specific function
from utils import add

print(add(5, 7))

# Rename import
from utils import add as add_numbers

print(add_numbers(1, 2))


# Built-in modules
import math

print(math.sqrt(16))
print(math.pi)


# Pitfall: naming conflicts
# utils.py vs built-in names