"""
Topic: Dataclasses
Goal: Simplify class creation
Level: Intermediate
"""

from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int


u = User("Alice", 25)

print(u)
# Output: User(name='Alice', age=25)

# No need to write __init__ manually