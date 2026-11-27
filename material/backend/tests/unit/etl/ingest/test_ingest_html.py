import asyncio
from unittest.mock import MagicMock, patch

from etl.ingest.ingest_html import HTMLIngest
from etl.models import DataType


class TestHTMLIngestInit:
    def test_stores_path(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=None, path="/unused")

        assert ingest._path == "/unused"

    def test_path_defaults_to_empty_string(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=None)

        assert ingest._path == ""

    def test_stores_repository(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=None)

        assert ingest._repo is mock_repo

    def test_stores_objects_list(self):
        mock_repo = MagicMock()
        objects = ["http://example.com/page1", "http://example.com/page2"]

        ingest = HTMLIngest(mock_repo, objects=objects)

        assert ingest._objects == objects


class TestHTMLIngestIngestNoObjects:
    def test_returns_empty_list_when_no_objects(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=None)
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_does_not_call_repo_get_when_no_objects(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=None)
        asyncio.run(ingest.ingest())

        mock_repo.get.assert_not_called()

    def test_logs_warning_when_no_objects(self):
        mock_repo = MagicMock()
        ingest = HTMLIngest(mock_repo, objects=None)

        with patch.object(ingest, "logger") as mock_logger:
            asyncio.run(ingest.ingest())

            mock_logger.warning.assert_called_once()

    def test_returns_empty_list_for_empty_objects_list(self):
        mock_repo = MagicMock()

        ingest = HTMLIngest(mock_repo, objects=[])
        result = asyncio.run(ingest.ingest())

        assert result == []


class TestHTMLIngestIngest:
    def test_fetches_each_object(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        objects = ["http://example.com/page1", "http://example.com/page2"]

        ingest = HTMLIngest(mock_repo, objects=objects)
        asyncio.run(ingest.ingest())

        assert mock_repo.get.call_count == 2

    def test_skips_none_items(self):
        mock_repo = MagicMock()
        mock_repo.get.return_value = None

        ingest = HTMLIngest(mock_repo, objects=["http://missing.com"])
        result = asyncio.run(ingest.ingest())

        assert result == []

    def test_creates_pipeline_item_with_correct_name(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "page.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://example.com/page.html"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["http://example.com/page.html"])
        result = asyncio.run(ingest.ingest())

        assert result[0].name == "page.html"

    def test_creates_pipeline_item_with_correct_data_id(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "unique_html_id"
        mock_item.name = "page.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://example.com"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["url"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_id == "unique_html_id"

    def test_source_object_has_html_data_type(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "page.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://example.com"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["url"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.data_type == DataType.HTML

    def test_data_object_has_html_data_type(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "page.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://example.com"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["url"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.data_type == DataType.HTML

    def test_source_object_source_from_descriptor_name(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "page.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://example.com/full/path/page.html"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["url"])
        result = asyncio.run(ingest.ingest())

        assert result[0].source_object.source == "http://example.com/full/path/page.html"

    def test_data_object_contains_html_content(self):
        mock_repo = MagicMock()
        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "page.html"
        mock_item.data = "<html><body>Hello World</body></html>"
        mock_item.descriptor.name = "http://example.com"
        mock_repo.get.return_value = mock_item

        ingest = HTMLIngest(mock_repo, objects=["url"])
        result = asyncio.run(ingest.ingest())

        assert result[0].data_object.data == "<html><body>Hello World</body></html>"

    def test_handles_multiple_urls(self):
        mock_repo = MagicMock()

        def create_mock_item(name, url):
            item = MagicMock()
            item.id = f"id_{name}"
            item.name = name
            item.data = f"<html>{name}</html>"
            item.descriptor.name = url
            return item

        mock_repo.get.side_effect = [
            create_mock_item("page1.html", "http://example.com/page1"),
            create_mock_item("page2.html", "http://example.com/page2"),
        ]

        ingest = HTMLIngest(mock_repo, objects=["url1", "url2"])
        result = asyncio.run(ingest.ingest())

        assert len(result) == 2
        assert result[0].name == "page1.html"
        assert result[1].name == "page2.html"

    def test_mixed_none_and_valid_items(self):
        mock_repo = MagicMock()

        mock_item = MagicMock()
        mock_item.id = "id"
        mock_item.name = "valid.html"
        mock_item.data = "<html></html>"
        mock_item.descriptor.name = "http://valid.com"

        mock_repo.get.side_effect = [None, mock_item, None]

        ingest = HTMLIngest(mock_repo, objects=["missing1", "valid", "missing2"])
        result = asyncio.run(ingest.ingest())

        assert len(result) == 1
        assert result[0].name == "valid.html"
