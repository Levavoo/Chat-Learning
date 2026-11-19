"""
Topic: Polymorphism
Goal: Same interface, different behavior
Level: Intermediate
"""

class Bird:
    def speak(self):
        print("Chirp")


class Dog:
    def speak(self):
        print("Bark")


def make_sound(animal):
    animal.speak()


make_sound(Bird())
make_sound(Dog())

# Output:
# Chirp
# Bark