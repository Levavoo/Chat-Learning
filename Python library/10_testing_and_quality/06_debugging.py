"""
Topic: Debugging
Goal: Find and fix bugs
"""

def divide(a, b):
    return a / b

# Debugging approach
print(divide(10, 2))

# breakpoint
def test():
    x = 5
    breakpoint()  # inspect variables
    return x * 2

# test()