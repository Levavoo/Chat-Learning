"""
Topic: itertools
"""

import itertools

# count
for i in itertools.count(0, 2):
    if i > 6:
        break
    print(i)

# combinations
print(list(itertools.combinations([1, 2, 3], 2)))

# permutations
print(list(itertools.permutations([1, 2, 3], 2)))