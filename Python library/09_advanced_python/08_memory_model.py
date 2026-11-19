"""
Topic: Memory Model
Goal: Understand references and memory
"""

# Everything is object reference
a = [1, 2, 3]
b = a

b.append(4)

print(a)  # [1,2,3,4]

# Copy
import copy

c = copy.copy(a)
d = copy.deepcopy(a)

# id shows memory address
print(id(a), id(b))