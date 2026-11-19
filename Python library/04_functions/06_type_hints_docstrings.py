"""
Topic: Type Hints and Docstrings
Goal: Write clearer, self-documented functions
Level: Beginner → Intermediate
"""

def add(a: int, b: int) -> int:
    """Add two integers and return result"""
    return a + b

print(add(2, 3))


def greet(name: str) -> str:
    """Return greeting message"""
    return f"Hello, {name}"


# Type hints do NOT enforce types at runtime
print(add("2", "3"))  # works but not intended


# Better documentation
def divide(a: float, b: float) -> float:
    """
    Divide two numbers.

    Args:
        a: numerator
        b: denominator

    Returns:
        result of division
    """
    return a / b