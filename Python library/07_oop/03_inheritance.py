"""
Topic: Inheritance
Goal: Reuse code from parent classes
Level: Beginner → Intermediate
"""

class Animal:
    def __init__(self, name):
        self.name = name

    def speak(self):
        print("Some sound")


class Dog(Animal):
    def speak(self):
        print("Bark")


class Cat(Animal):
    def speak(self):
        print("Meow")


dog = Dog("Buddy")
cat = Cat("Milo")

dog.speak()  # Bark
cat.speak()  # Meow