"""
Topic: Instance vs Class Attributes
Goal: Understand attribute differences
Level: Beginner
"""

class Dog:
    species = "Canine"  # class attribute

    def __init__(self, name):
        self.name = name  # instance attribute


d1 = Dog("Buddy")
d2 = Dog("Max")

print(d1.species)
print(d2.species)

d1.species = "Wolf"

print(d1.species)  # Wolf
print(d2.species)  # Canine

# Pitfall: class attributes are shared unless overridden