import asyncio
from unittest.mock import MagicMock

from etl.ingest.s3 import S3Ingest
from etl.models import DataType


class TestS3IngestInit:
    def test_stores_path_as_root_dir(self):
        mock_repo = MagicMock()

        ingest = S3Ingest(mock_repo, objects=None, path="/bucket/prefix")

        assert ingest._root_dir == "/bucket/prefix"

    def test_root_dir_defaults_to_empty_string(self):
        mock_repo = MagicMock()

        ingest = S3Ingest(mock_repo, objects=None)

        assert ingest._root_dir == ""

    def test_stores_repository(self):
        mock_repo = MagicMock()

        ingest = S3Ingest(mock_repo, objects=None)

        assert ingest._repo is mock_repo

    def test_stores_objects_list(self):
        mock_repo = MagicMock()
        objects = ["key1", "key2"]

        ingest = S3Ingest(mock_repo, objects=objects)

        assert ingest._objects == objects


class TestS3IngestIngest:
    def test_uses_objects_list_when_provided(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        objects = ["key1", "key2"]

        ingest = S3Ingest(mock_repo, objects=objects)
        asyncio.run(ingest.ingest())

        mock_repo.list_items.assert_not_called()
        assert mock_repo.get.call_count == 2

    def test_lists_objects_when_objects_not_provided(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.object_id = "listed_key"
        mock_repo.list_items.return_value = [mock_item]
        mock_repo.get.return_value = None

        ingest = S3Ingest(mock_repo, objects=None, path="prefix/")
        asyncio.run(ingest.ingest())

        mock_repo.list_items.assert_called_once_with(path="prefix/")

    def test_filters_none_items(self):
        mock_repo = MagicMock()
        mock_repo.get.side_effect = [None, None]

        ingest = S3Ingest(mock_repo, objects=["key1", "key2"])
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_returns_empty_list_when_no_objects(self):
        mock_repo = MagicMock()
        mock_repo.list_items.return_value = []

        ingest = S3Ingest(mock_repo, objects=None)
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_creates_pipeline_item_with_correct_name(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.name = "document.pdf"
        mock_item.data = b"content"
        mock_item.metadata = {}
        mock_item.descriptor.file_extension = ".pdf"
        mock_item.descriptor.bucket_name = "bucket"
        mock_repo.get.return_value = mock_item

        ingest = S3Ingest(mock_repo, objects=["document.pdf"])
        result = asyncio.run(ingest.ingest())

        assert result[0].name == "document.pdf"

    def test_creates_source_object_with_s3_url(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.name = "path/to/file.json"
        mock_item.data = b"{}"
        mock_item.metadata = {}
        mock_item.descriptor.file_extension = ".json"
        mock_item.descriptor.bucket_name = "my-bucket"
        mock_repo.get.return_value = mock_item

        ingest = S3Ingest(mock_repo, objects=["path/to/file.json"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.source == "s3://my-bucket/path/to/file.json"

    def test_creates_data_object_with_correct_data_type(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.name = "report.pdf"
        mock_item.data = b"pdf content"
        mock_item.metadata = {}
        mock_item.descriptor.file_extension = ".pdf"
        mock_item.descriptor.bucket_name = "bucket"
        mock_repo.get.return_value = mock_item

        ingest = S3Ingest(mock_repo, objects=["report.pdf"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.data_type == DataType.PDF

    def test_preserves_item_metadata(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.name = "file.txt"
        mock_item.data = b"content"
        mock_item.metadata = {"size": 1024, "etag": "abc123"}
        mock_item.descriptor.file_extension = ".txt"
        mock_item.descriptor.bucket_name = "bucket"
        mock_repo.get.return_value = mock_item

        ingest = S3Ingest(mock_repo, objects=["file.txt"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.metadata == {"size": 1024, "etag": "abc123"}
        assert result[0].data_object.metadata == {"size": 1024, "etag": "abc123"}

    def test_handles_multiple_objects(self):
        mock_repo = MagicMock()

        def create_mock_item(name, ext):
            item = MagicMock()
            item.name = name
            item.data = f"content of {name}".encode()
            item.metadata = {}
            item.descriptor.file_extension = ext
            item.descriptor.bucket_name = "bucket"
            return item

        mock_repo.get.side_effect = [
            create_mock_item("file1.txt", ".txt"),
            create_mock_item("file2.json", ".json"),
        ]

        ingest = S3Ingest(mock_repo, objects=["file1.txt", "file2.json"])
        result = asyncio.run(ingest.ingest())

        assert len(result) == 2
        assert result[0].name == "file1.txt"
        assert result[1].name == "file2.json"

    def test_mixed_none_and_valid_items(self):
        mock_repo = MagicMock()

        mock_item = MagicMock()
        mock_item.name = "valid.txt"
        mock_item.data = b"content"
        mock_item.metadata = {}
        mock_item.descriptor.file_extension = ".txt"
        mock_item.descriptor.bucket_name = "bucket"

        mock_repo.get.side_effect = [None, mock_item, None]

        ingest = S3Ingest(mock_repo, objects=["missing1", "valid.txt", "missing2"])
        result = asyncio.run(ingest.ingest())

        assert len(result) == 1
        assert result[0].name == "valid.txt"


class TestS3IngestSpaceStripping:
    """Write path uses data_object.name as the chunk folder name; _compute_stem in
    lambda_function.py also strips spaces. Both sides must produce the same stem so
    list_by_stem can locate stale artifacts during replace/delete flows."""

    def _make_spaced_item(self, name: str) -> MagicMock:
        item = MagicMock()
        item.name = name
        item.data = b"content"
        item.metadata = {}
        item.descriptor.file_extension = ".xml"
        item.descriptor.bucket_name = "bucket"
        return item

    def test_spaces_stripped_from_data_object_name(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = self._make_spaced_item("FB 28")

        ingest = S3Ingest(mock_repo, objects=["IN/FB 28.xml"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.name == "FB28"

    def test_spaces_stripped_from_source_object_name(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = self._make_spaced_item("FB 28")

        ingest = S3Ingest(mock_repo, objects=["IN/FB 28.xml"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.name == "FB28"

    def test_source_url_still_contains_original_key(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = self._make_spaced_item("FB 28")

        ingest = S3Ingest(mock_repo, objects=["IN/FB 28.xml"])
        result = asyncio.run(ingest.ingest())

        assert "FB 28" in result[0].source_object.source

    def test_stem_parity_with_compute_stem(self):
        from etl.lambda_function import _compute_stem

        mock_repo = MagicMock()
        mock_repo.get.return_value = self._make_spaced_item("FB 28")

        ingest = S3Ingest(mock_repo, objects=["IN/FB 28.xml"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.name == _compute_stem("IN/FB 28.xml")

    def test_no_spaces_case_unchanged(self):
        mock_repo = MagicMock()
        item = MagicMock()
        item.name = "B01"
        item.data = b"content"
        item.metadata = {}
        item.descriptor.file_extension = ".xml"
        item.descriptor.bucket_name = "bucket"
        mock_repo.get.return_value = item

        ingest = S3Ingest(mock_repo, objects=["IN/B01.xml"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.name == "B01"
