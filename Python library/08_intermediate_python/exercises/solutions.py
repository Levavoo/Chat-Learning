"""
Reference solutions
"""

# 2 generator
def even_gen(n):
    for i in range(n):
        if i % 2 == 0:
            yield i

print(list(even_gen(10)))


# 3 decorator
import time

def timer(func):
    def wrapper():
        start = time.time()
        func()
        print(time.time() - start)
    return wrapper


# 7 Counter
from collections import Counter
text = "a b a c a"
print(Counter(text.split()))


# 9 reduce
from functools import reduce
print(reduce(lambda x, y: x*y, [1,2,3,4]))