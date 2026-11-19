"""
Reference solutions
"""

# 1
class Car:
    wheels = 4

    def __init__(self, brand, speed=0):
        self.brand = brand
        self.speed = speed

    def accelerate(self, amount):
        self.speed += amount


# 2 already included


# 3
class Animal:
    def speak(self):
        print("sound")

class Dog(Animal):
    def speak(self):
        print("bark")


# 4
class A:
    def act(self):
        print("A")

class B:
    def act(self):
        print("B")

def run(obj):
    obj.act()


# 5
class Item:
    def __str__(self):
        return "Item object"


# 6
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int


# 7
class Product:
    def __init__(self, price):
        self._price = price

    @property
    def price(self):
        return self._price

    @price.setter
    def price(self, value):
        if value < 0:
            raise ValueError("Invalid")
        self._price = value