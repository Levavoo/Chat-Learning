"""
Topic: Assertions
Goal: Basic checks in code
"""

def add(a, b):
    return a + b

result = add(2, 3)

assert result == 5
# passes

# assert result == 6  # raises AssertionError


# Use in debugging
x = 10
assert x > 0, "x must be positive"