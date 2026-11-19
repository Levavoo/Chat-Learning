"""
Reference solutions
"""

# 1
def square(x):
    return x**2

assert square(3) == 9


# 2 pytest example
def test_square():
    assert square(2) == 4


# 3 fixture example (see pytest file)


# 4 mock
from unittest.mock import Mock

mock = Mock(return_value=42)
print(mock())


# 5 logging
import logging
logging.basicConfig(level=logging.INFO)
logging.info("Hello")


# 6 debugging
def f():
    x = 10
    breakpoint()
    return x