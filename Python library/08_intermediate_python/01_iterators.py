"""
Topic: Iterators
Goal: Understand iteration protocol
"""

numbers = [1, 2, 3]

iterator = iter(numbers)

print(next(iterator))  # 1
print(next(iterator))  # 2
print(next(iterator))  # 3
# next(iterator) -> StopIteration

# Loop uses iterator internally
for n in numbers:
    print(n)