
from unittest.mock import MagicMock, patch

import pytest

from etl.util.repository.base import Repository
from etl.util.repository.html_scrape import HTMLItem, HTMLObject, HTMLRepository


class TestHTMLObject:

    def test_create_with_required_fields(self):
        obj = HTMLObject(object_id="page.html", name="page")
        assert obj.object_id == "page.html"
        assert obj.name == "page"
        assert obj.metadata == {}

    def test_inherits_from_repository_object(self):
        obj = HTMLObject(
            object_id="test.html",
            name="test",
            metadata={"key": "value"},
        )
        assert obj.metadata == {"key": "value"}


class TestHTMLItem:

    def test_create_html_item(self, sample_data):
        desc = HTMLObject(object_id="page.html", name="page")
        item = HTMLItem(descriptor=desc, data=sample_data)
        assert item.data == sample_data
        assert item.id == "page.html"
        assert item.name == "page"

    def test_inherits_repository_item_properties(self, sample_data, sample_metadata):
        desc = HTMLObject(object_id="page.html", name="page", metadata=sample_metadata)
        item = HTMLItem(descriptor=desc, data=sample_data)
        assert item.metadata == sample_metadata


class TestHTMLRepository:

    def test_init_normalizes_root_url_with_trailing_slash(self):
        repo = HTMLRepository("https://example.com")
        assert repo.root_url == "https://example.com/"

    def test_init_preserves_existing_trailing_slash(self):
        repo = HTMLRepository("https://example.com/")
        assert repo.root_url == "https://example.com/"

    def test_init_handles_path_in_url(self):
        repo = HTMLRepository("https://example.com/api/v1")
        assert repo.root_url == "https://example.com/api/v1/"

    def test_list_raises_not_implemented(self):
        repo = HTMLRepository("https://example.com")
        with pytest.raises(NotImplementedError, match="not supported"):
            repo.list_items()

    @patch("requests.get")
    def test_get_returns_html_content(self, mock_get, sample_data):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = sample_data
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        item = repo.get("page.html")

        assert item.data == sample_data
        mock_get.assert_called_once_with("https://example.com/page.html", timeout=30)

    @patch("requests.get")
    def test_get_constructs_correct_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"content"
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com/docs")
        repo.get("api/endpoint.html")

        mock_get.assert_called_once_with("https://example.com/docs/api/endpoint.html", timeout=30)

    @patch("requests.get")
    def test_get_strips_leading_slash_from_object_id(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"content"
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        repo.get("/page.html")

        mock_get.assert_called_once_with("https://example.com/page.html", timeout=30)

    @patch("requests.get")
    def test_get_returns_correct_descriptor(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"<html></html>"
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        item = repo.get("folder/page.html")

        assert item.descriptor.object_id == "folder/page.html"
        assert item.descriptor.name == "page.html"
        assert item.descriptor.metadata["source_url"] == "https://example.com/folder/page.html"

    @patch("requests.get")
    def test_get_failed_request_raises_value_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        with pytest.raises(ValueError, match="Failed to retrieve"):
            repo.get("nonexistent.html")

    @patch("requests.get")
    def test_get_server_error_raises_value_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        with pytest.raises(ValueError, match="Failed to retrieve"):
            repo.get("error.html")

    @patch("requests.get")
    def test_get_handles_binary_content(self, mock_get):
        binary_content = bytes(range(256))
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = binary_content
        mock_get.return_value = mock_response

        repo = HTMLRepository("https://example.com")
        item = repo.get("file.bin")

        assert item.data == binary_content

    def test_put_raises_not_implemented(self, sample_data):
        repo = HTMLRepository("https://example.com")
        desc = HTMLObject(object_id="page.html", name="page")
        item = HTMLItem(descriptor=desc, data=sample_data)

        with pytest.raises(NotImplementedError, match="not supported"):
            repo.put(item)


class TestHTMLRepositoryFactory:

    def test_create_html_repository(self):
        repo = Repository.create("HTML", root_url="https://example.com")
        assert isinstance(repo, HTMLRepository)
        assert repo.root_url == "https://example.com/"
