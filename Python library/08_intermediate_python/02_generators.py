"""
Topic: Generators
Goal: Yield values lazily
"""

def count_up(n):
    i = 0
    while i < n:
        yield i
        i += 1

gen = count_up(3)

print(next(gen))  # 0
print(next(gen))  # 1
print(next(gen))  # 2

# Generator expression
squares = (x**2 for x in range(5))
print(list(squares))  # [0,1,4,9,16]

# Benefit: memory efficient