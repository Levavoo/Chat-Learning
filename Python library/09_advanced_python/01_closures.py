"""
Topic: Closures
Goal: Functions remembering outer variables
"""

def outer(x):
    def inner(y):
        return x + y
    return inner

add_five = outer(5)

print(add_five(3))  # 8
print(add_five(10)) # 15

# x is remembered inside inner()

# Practical example
def counter():
    count = 0
    def increment():
        nonlocal count
        count += 1
        return count
    return increment

c = counter()
print(c())  # 1
print(c())  # 2