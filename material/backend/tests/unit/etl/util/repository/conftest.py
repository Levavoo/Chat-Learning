
import pytest


@pytest.fixture
def sample_data() -> bytes:
    return b"test content data"


@pytest.fixture
def sample_metadata() -> dict:
    return {"key1": "value1", "key2": "value2"}
