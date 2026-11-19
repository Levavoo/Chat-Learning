"""
Topic: Descriptors
Goal: Control attribute access
"""

class Descriptor:
    def __get__(self, instance, owner):
        return "value"

    def __set__(self, instance, value):
        print("Setting value:", value)


class MyClass:
    attr = Descriptor()

obj = MyClass()

print(obj.attr)     # value
obj.attr = 10       # Setting value: 10