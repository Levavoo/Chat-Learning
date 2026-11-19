"""
Topic: __slots__
Goal: Optimize memory usage
"""

class Normal:
    def __init__(self, x):
        self.x = x


class Slotted:
    __slots__ = ["x"]

    def __init__(self, x):
        self.x = x


# Slotted objects use less memory