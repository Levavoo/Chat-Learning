"""
Topic: *args and **kwargs
Goal: Flexible function arguments
Level: Beginner → Intermediate
"""

# *args = multiple positional arguments
def sum_all(*args):
    total = 0
    for num in args:
        total += num
    return total

print(sum_all(1, 2, 3, 4))
# Output: 10


# **kwargs = multiple named arguments
def print_user(**kwargs):
    for key, value in kwargs.items():
        print(key, value)

print_user(name="Alice", age=25)


# Combination
def example(a, *args, **kwargs):
    print("a:", a)
    print("args:", args)
    print("kwargs:", kwargs)

example(1, 2, 3, x=10, y=20)


# Pitfall: order matters
# def wrong(*args, a):  # invalid
#     pass