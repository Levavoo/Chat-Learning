"""
Topic: property / staticmethod / classmethod
Goal: Advanced class methods
Level: Intermediate
"""

class Circle:
    def __init__(self, radius):
        self._radius = radius

    @property
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        if value < 0:
            raise ValueError("Radius must be positive")
        self._radius = value

    @staticmethod
    def area_formula(r):
        return 3.14 * r * r

    @classmethod
    def from_diameter(cls, diameter):
        return cls(diameter / 2)


c = Circle(5)
print(c.radius)

c.radius = 10
print(c.radius)

print(Circle.area_formula(3))

c2 = Circle.from_diameter(10)
print(c2.radius)