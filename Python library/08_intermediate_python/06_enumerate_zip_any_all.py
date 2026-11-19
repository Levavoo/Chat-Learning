"""
Topic: enumerate, zip, any, all
"""

# enumerate
names = ["a", "b", "c"]
for i, name in enumerate(names):
    print(i, name)

# zip
a = [1, 2]
b = ["x", "y"]
for x, y in zip(a, b):
    print(x, y)

# any
nums = [0, 0, 1]
print(any(nums))  # True

# all
nums = [1, 2, 3]
print(all(nums))  # True