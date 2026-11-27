import asyncio
from unittest.mock import MagicMock

from etl.models import DataType
from etl.output.local_file import LocalFileOutput


class TestLocalFileOutputInit:
    def test_stores_file_system(self):
        mock_fs = MagicMock()

        output = LocalFileOutput(mock_fs)

        assert output._file_system is mock_fs

    def test_stores_path(self):
        mock_fs = MagicMock()

        output = LocalFileOutput(mock_fs, path="/output/path")

        assert output._path == "/output/path"

    def test_path_defaults_to_empty_string(self):
        mock_fs = MagicMock()

        output = LocalFileOutput(mock_fs)

        assert output._path == ""


class TestLocalFileOutputExport:
    def _create_pipeline_item(
        self,
        name="test.txt",
        data_id="item_id",
        data: bytes | str = b"content",
        data_type=DataType.TEXT,
        source="/path/to/source.txt",
        metadata=None,
    ):
        item = MagicMock()
        item.name = name
        item.data_id = data_id
        item.data_object.data = data
        item.data_object.data_type = data_type
        item.data_object.metadata = metadata or {}
        item.data_object.name = name
        item.source_object.source = source
        return item

    def test_calls_put_on_file_system(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs, path="/output")
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        mock_fs.put.assert_called_once()

    def test_put_receives_path_argument(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs, path="/custom/output")
        item = self._create_pipeline_item()

        asyncio.run(output.export(item))

        call_kwargs = mock_fs.put.call_args.kwargs
        assert call_kwargs["path"] == "/custom/output"

    def test_returns_output_data_with_correct_name(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(name="document.pdf")

        result = asyncio.run(output.export(item))

        assert result.name == "document.pdf"

    def test_returns_output_data_with_correct_output_id(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(data_id="unique_id_123")

        result = asyncio.run(output.export(item))

        assert result.output_id == "unique_id_123"

    def test_returns_output_data_with_output_path(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item()

        result = asyncio.run(output.export(item))

        assert isinstance(result.output_path, str)

    def test_encodes_string_data_to_bytes(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(data=b"string content")

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.data == b"string content"

    def test_preserves_bytes_data(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(data=b"binary content")

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.data == b"binary content"

    def test_creates_file_object_with_correct_object_id(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(data_id="my_object_id")

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.descriptor.object_id == "my_object_id"

    def test_creates_file_object_with_correct_name(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(name="output_file.json")

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.descriptor.name == "output_file.json"

    def test_creates_file_object_with_data_type_extension(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(data_type=DataType.JSON)

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.descriptor.file_extension == DataType.JSON.value

    def test_creates_file_object_with_source_path(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(source="/original/source/file.txt")

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.descriptor.file_path == "/original/source/file.txt"

    def test_creates_file_object_with_metadata(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item(metadata={"author": "test", "version": 1})

        asyncio.run(output.export(item))

        call_args = mock_fs.put.call_args.args
        file_item = call_args[0]
        assert file_item.descriptor.metadata == {"author": "test", "version": 1}

    def test_returns_empty_metadata_in_output_data(self):
        mock_fs = MagicMock()
        output = LocalFileOutput(mock_fs)
        item = self._create_pipeline_item()

        result = asyncio.run(output.export(item))

        assert result.metadata == {}
