"""
Topic: pytest basics
Goal: Write automated tests
"""

# file: test_math.py

def add(a, b):
    return a + b


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0