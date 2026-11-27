
import pytest

from etl.util.chunking.base import Chunk, ChunkingStrategy


class TestChunk:

    def test_create_with_content_only(self):
        chunk = Chunk(content="test content")
        assert chunk.content == "test content"
        assert chunk.metadata == {}

    def test_create_with_content_and_metadata(self, base_metadata):
        chunk = Chunk(content="test", metadata=base_metadata)
        assert chunk.content == "test"
        assert chunk.metadata == base_metadata

    def test_metadata_default_is_empty_dict(self):
        chunk1 = Chunk(content="a")
        chunk2 = Chunk(content="b")
        chunk1.metadata["key"] = "value"
        assert "key" not in chunk2.metadata

    def test_metadata_is_mutable(self):
        chunk = Chunk(content="test")
        chunk.metadata["new_key"] = "new_value"
        assert chunk.metadata["new_key"] == "new_value"


class TestChunkingStrategy:

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError, match="abstract"):
            ChunkingStrategy()

    def test_subclass_must_implement_chunk_method(self):

        class IncompleteStrategy(ChunkingStrategy):
            pass

        with pytest.raises(TypeError, match="abstract"):
            IncompleteStrategy()
