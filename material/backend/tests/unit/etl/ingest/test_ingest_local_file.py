import asyncio
from unittest.mock import MagicMock

from etl.ingest.local_file import LocalFileIngest


class TestLocalFileIngestInit:
    def test_stores_path(self):
        mock_repo = MagicMock()

        ingest = LocalFileIngest(mock_repo, objects=None, path="/test/path")

        assert ingest._path == "/test/path"

    def test_path_defaults_to_empty_string(self):
        mock_repo = MagicMock()

        ingest = LocalFileIngest(mock_repo, objects=None)

        assert ingest._path == ""

    def test_stores_repository(self):
        mock_repo = MagicMock()

        ingest = LocalFileIngest(mock_repo, objects=None)

        assert ingest._repo is mock_repo

    def test_stores_objects_list(self):
        mock_repo = MagicMock()
        objects = ["file1.txt", "file2.txt"]

        ingest = LocalFileIngest(mock_repo, objects=objects)

        assert ingest._objects == objects


class TestLocalFileIngestIngest:
    def test_uses_objects_list_when_provided(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        objects = ["file1.txt", "file2.txt"]

        ingest = LocalFileIngest(mock_repo, objects=objects)
        asyncio.run(ingest.ingest())

        mock_repo.list_items.assert_not_called()
        assert mock_repo.get.call_count == 2

    def test_lists_files_when_objects_not_provided(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.object_id = "listed_file.txt"
        mock_repo.list_items.return_value = [mock_item]
        mock_repo.get.return_value = None

        ingest = LocalFileIngest(mock_repo, objects=None, path="/search")
        asyncio.run(ingest.ingest())

        mock_repo.list_items.assert_called_once_with(path="/search")

    def test_skips_none_items(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None

        ingest = LocalFileIngest(mock_repo, objects=["missing.txt"])
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_returns_empty_list_when_no_files(self):
        mock_repo = MagicMock()
        mock_repo.list_items.return_value = []

        ingest = LocalFileIngest(mock_repo, objects=None)
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_creates_pipeline_item_with_correct_name(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "item_id"
        mock_item.name = "test.txt"
        mock_item.file_path = "/path/to/test.txt"
        mock_item.file_extension = ".txt"
        mock_item.data = b"content"
        mock_repo.get.return_value = mock_item

        ingest = LocalFileIngest(mock_repo, objects=["test.txt"])
        result = asyncio.run(ingest.ingest())

        assert result[0].name == "test.txt"

    def test_creates_pipeline_item_with_correct_data_id(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "unique_item_id"
        mock_item.name = "test.txt"
        mock_item.file_path = "/path/to/test.txt"
        mock_item.file_extension = ".txt"
        mock_item.data = b"content"
        mock_repo.get.return_value = mock_item

        ingest = LocalFileIngest(mock_repo, objects=["test.txt"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_id == "unique_item_id"

    def test_creates_source_object_with_file_path(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "test.txt"
        mock_item.file_path = "/absolute/path/to/test.txt"
        mock_item.file_extension = ".txt"
        mock_item.data = b"content"
        mock_repo.get.return_value = mock_item

        ingest = LocalFileIngest(mock_repo, objects=["test.txt"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.source == "/absolute/path/to/test.txt"

    def test_creates_data_object_with_file_content(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "test.txt"
        mock_item.file_path = "/path/test.txt"
        mock_item.file_extension = ".txt"
        mock_item.data = b"file content here"
        mock_repo.get.return_value = mock_item

        ingest = LocalFileIngest(mock_repo, objects=["test.txt"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.data == b"file content here"

    def test_handles_multiple_files(self):
        mock_repo = MagicMock()

        def create_mock_item(name):
            item = MagicMock()
            item.id = f"id_{name}"
            item.name = name
            item.file_path = f"/path/{name}"
            item.file_extension = ".txt"
            item.data = f"content of {name}".encode()
            return item

        mock_repo.get.side_effect = [
            create_mock_item("file1.txt"),
            create_mock_item("file2.txt"),
            create_mock_item("file3.txt"),
        ]

        ingest = LocalFileIngest(mock_repo, objects=["file1.txt", "file2.txt", "file3.txt"])
        result = asyncio.run(ingest.ingest())

        assert len(result) == 3
        assert result[0].name == "file1.txt"
        assert result[1].name == "file2.txt"
        assert result[2].name == "file3.txt"
