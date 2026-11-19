"""
Topic: Classes and Objects
Goal: Create and use basic classes
Level: Beginner
"""

# Define class
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age

    def greet(self):
        print(f"Hello, my name is {self.name}")


# Create object
p1 = Person("Alice", 25)

print(p1.name)  # Alice
print(p1.age)   # 25

p1.greet()
# Output: Hello, my name is Alice