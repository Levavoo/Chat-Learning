import asyncio
from unittest.mock import MagicMock

from etl.models import DataType
from etl.output.s3 import S3BucketOutput


class TestS3BucketOutputInit:
    def test_stores_repository(self):
        mock_repo = MagicMock()

        output = S3BucketOutput(mock_repo)

        assert output._repository is mock_repo

    def test_stores_path(self):
        mock_repo = MagicMock()

        output = S3BucketOutput(mock_repo, path="prefix/output")

        assert output._path == "prefix/output"

    def test_path_defaults_to_empty_string(self):
        mock_repo = MagicMock()

        output = S3BucketOutput(mock_repo)

        assert output._path == ""


class TestS3BucketOutputExport:
    def _create_pipeline_item(
        self,
        name="test.txt",
        data_id="item_id",
        data: bytes | str = b"content",
        data_type=DataType.TEXT,
        data_name="data_object_name",
        metadata=None,
    ):
        item = MagicMock()
        item.name = name
        item.data_id = data_id
        item.data_object.data = data
        item.data_object.data_type = data_type
        item.data_object.name = data_name
        item.data_object.metadata = metadata or {}
        return item

    def test_calls_put_on_repository(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "test-bucket"
        output = S3BucketOutput(mock_repo, path="output/")
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        mock_repo.put.assert_called_once()

    def test_put_receives_sub_path_argument(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo, path="custom/prefix")
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        call_kwargs = mock_repo.put.call_args.kwargs
        assert call_kwargs["sub_path"] == "custom/prefix"

    def test_returns_output_data_with_correct_name(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(name="document.pdf")

        result = asyncio.run(output.export(item))

        assert result.name == "document.pdf"

    def test_returns_output_data_with_correct_output_id(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(data_id="unique_s3_id")

        result = asyncio.run(output.export(item))

        assert result.output_id == "unique_s3_id"

    def test_returns_output_data_with_empty_output_path(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item()

        result = asyncio.run(output.export(item))

        assert result.output_path == ""

    def test_encodes_string_data_to_bytes(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(data="string content")

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.data == b"string content"

    def test_preserves_bytes_data(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(data=b"binary content")

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.data == b"binary content"

    def test_creates_s3_object_with_data_object_name_as_object_id(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(data_name="data_object_identifier")

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.object_id == "data_object_identifier"

    def test_creates_s3_object_with_correct_name(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(name="output_file.json")

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.name == "output_file.json"

    def test_creates_s3_object_with_data_type_extension(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(data_type=DataType.JSON)

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.file_extension == DataType.JSON.value

    def test_creates_s3_object_with_empty_etag(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.etag == ""

    def test_creates_s3_object_with_empty_bucket_name(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.bucket_name == ""

    def test_creates_s3_object_with_metadata(self):
        mock_repo = MagicMock()
        mock_repo.bucket_name = "bucket"
        output = S3BucketOutput(mock_repo)
        item = self._create_pipeline_item(metadata={"key": "value", "count": 42})

        asyncio.run(output.export(item))

        call_args = mock_repo.put.call_args.args
        s3_item = call_args[0]
        assert s3_item.descriptor.metadata == {"key": "value", "count": 42}
