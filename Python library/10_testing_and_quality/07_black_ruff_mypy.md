# Code Quality Tools

## black (formatter)

Formats code automatically:

```bash
black .

Finds errors and bad practices:

ruff check .

Checks type hints:

mypy .

## `10_testing_and_quality/tests/test_example.py`

```python
def multiply(a, b):
    return a * b


def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(0, 5) == 0