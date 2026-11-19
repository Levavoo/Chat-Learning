"""
Topic: Scope
Goal: Understand variable visibility
Level: Beginner → Intermediate
"""

# Local scope
def my_function():
    x = 10
    print(x)

my_function()

# print(x)  # Error


# Global variable
x = 5

def show():
    print(x)

show()  # Output: 5


# Modifying global (not recommended)
counter = 0

def increase():
    global counter
    counter += 1

increase()
print(counter)


# Better approach: return value
def increase_safe(n):
    return n + 1

counter = increase_safe(counter)


# Pitfall: shadowing
x = 10

def test():
    x = 5  # different variable
    print(x)

test()      # 5
print(x)    # 10