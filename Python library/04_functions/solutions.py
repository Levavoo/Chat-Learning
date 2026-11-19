"""
Reference solutions
"""

# 1
def square(x):
    return x**2


# 2
def describe(name, age):
    return f"{name} is {age} years old"


# 3
def print_val(x):
    print(x)

def return_val(x):
    return x


# 4
def max_value(*args):
    return max(args)


# 5
def show_user(**kwargs):
    for k, v in kwargs.items():
        print(k, v)


# 6
triple = lambda x: x * 3
print(list(map(triple, [1, 2, 3])))


# 7
data = [{"age": 30}, {"age": 20}]
print(sorted(data, key=lambda x: x["age"]))


# 8
nums = [5, 12, 3, 20]
print(list(filter(lambda x: x > 10, nums)))