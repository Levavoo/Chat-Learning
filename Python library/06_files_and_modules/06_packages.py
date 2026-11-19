"""
Topic: Packages
Goal: Organize code into folders
Level: Beginner → Intermediate
"""

# Example structure:
# my_package/
# ├── __init__.py
# ├── math_utils.py
# └── string_utils.py

# math_utils.py
def add(a, b):
    return a + b


# string_utils.py
def shout(text):
    return text.upper()


# Usage
# from my_package.math_utils import add
# from my_package.string_utils import shout

# print(add(2, 3))
# print(shout("hello"))


# __init__.py makes folder a package