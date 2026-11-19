"""
Topic: Mocking
Goal: Replace dependencies in tests
"""

from unittest.mock import Mock

# Example dependency
def get_data():
    return 10


def process():
    return get_data() * 2


# Mocking
mock = Mock(return_value=5)

get_data = mock

print(process())  # 10