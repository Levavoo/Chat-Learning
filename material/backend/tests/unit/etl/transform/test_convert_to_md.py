
import pytest

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.convert_to_md import text_to_md


def make_pipeline_item(
    content: bytes | str,
    name: str = "test-document",
    datatype: DataType = DataType.TEXT,
    metadata: dict | None = None,
) -> PipelineItem:
    return PipelineItem(
        name=name,
        data_object=DataObject(
            name=name,
            data_type=datatype,
            data=content,
            metadata=metadata or {},
        ),
    )


@pytest.fixture
def transform():
    return text_to_md()


@pytest.fixture
def sample_xml_content():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<root>
  <title>Test Document</title>
  <content>
    <paragraph>This is a test paragraph.</paragraph>
    <paragraph>Another paragraph here.</paragraph>
  </content>
</root>
"""


@pytest.fixture
def sample_html_content():
    return b"""<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Main Heading</h1>
  <p>This is a paragraph.</p>
  <ul>
    <li>Item 1</li>
    <li>Item 2</li>
  </ul>
</body>
</html>
"""


@pytest.fixture
def sample_plain_text():
    return b"This is plain text content.\nWith multiple lines."


@pytest.fixture
def sample_metadata():
    return {
        "title": "Test Document",
        "category": "testing",
        "keywords": ["test", "sample"],
        "brochure": "B00",
    }


class TestTextToMdApply:

    def test_apply_returns_list_of_pipeline_items(self, transform: text_to_md, sample_html_content):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML)
        result = transform.apply(item)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], PipelineItem)

    def test_output_type_is_markdown(self, transform: text_to_md, sample_html_content):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML)
        result = transform.apply(item)[0]
        assert result.data_object.data_type == DataType.MARKDOWN

    def test_output_content_is_string(self, transform, sample_html_content):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML)
        result = transform.apply(item)[0]
        assert isinstance(result.data_object.data, str)


class TestMarkItDownConversion:

    @pytest.mark.parametrize(
        ("content", "datatype", "expected_substring"),
        [
            pytest.param(
                b"<!DOCTYPE html><html><body><h1>Heading</h1><p>Para</p></body></html>",
                DataType.HTML,
                "Heading",
                id="html_to_markdown",
            ),
            pytest.param(
                b"This is plain text content.",
                DataType.TEXT,
                "This is plain text content.",
                id="plain_text_passthrough",
            ),
            pytest.param(
                b"Bytes input content",
                DataType.TEXT,
                "Bytes input content",
                id="handles_bytes_input",
            ),
            pytest.param(
                "String input content",
                DataType.TEXT,
                "String input content",
                id="handles_string_input",
            ),
        ],
    )
    def test_converts_content_to_markdown(self, transform, content, datatype, expected_substring):
        item = make_pipeline_item(content, datatype=datatype)
        result = transform.apply(item)[0]
        assert expected_substring in result.data_object.data  # pyright: ignore[reportOperatorIssue]


class TestBodyHasNoFrontmatter:
    """The body is pure Markdown: no YAML frontmatter is prepended (#696).

    Custom metadata must reach only the ``.metadata.json`` sidecar, so the body
    the KB embeds and BM25 returns is identical regardless of the metadata dict.
    """

    def test_output_does_not_start_with_frontmatter_delimiter(self, transform, sample_html_content, sample_metadata):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata=sample_metadata)
        result = transform.apply(item)[0]
        assert not str(result.data_object.data).startswith("---")

    def test_output_equals_stripped_converted_markdown(self, transform, sample_html_content, sample_metadata):
        from io import BytesIO

        from markitdown_no_magika import MarkItDown

        expected = MarkItDown().convert_stream(BytesIO(sample_html_content), file_extension=".html").markdown.strip()

        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata=sample_metadata)
        result = transform.apply(item)[0]
        assert result.data_object.data == expected

    def test_body_is_independent_of_metadata(self, transform, sample_html_content, sample_metadata):
        with_meta = transform.apply(
            make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata=sample_metadata)
        )[0]
        without_meta = transform.apply(make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata={}))[0]
        assert with_meta.data_object.data == without_meta.data_object.data

    def test_metadata_value_not_leaked_into_body(self, transform, sample_html_content, sample_metadata):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata=sample_metadata)
        result = transform.apply(item)[0]
        assert "B00" not in str(result.data_object.data)

    def test_metadata_dict_preserved_unchanged(self, transform, sample_html_content, sample_metadata):
        expected = dict(sample_metadata)
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML, metadata=sample_metadata)
        result = transform.apply(item)[0]
        assert result.data_object.metadata == expected

    def test_body_has_no_leading_or_trailing_whitespace(self, transform, sample_html_content):
        item = make_pipeline_item(sample_html_content, datatype=DataType.HTML)
        data = str(transform.apply(item)[0].data_object.data)
        assert data == data.strip()


class TestErrorHandling:

    def test_handles_empty_content(self, transform):
        item = make_pipeline_item(b"", datatype=DataType.TEXT)
        result = transform.apply(item)[0]
        data = str(result.data_object.data)
        assert not data.startswith("---")
        assert data == data.strip()
        assert data == ""

    def test_rejects_invalid_input_type(self, transform):
        item = make_pipeline_item(b"valid", datatype=DataType.TEXT)
        item.data_object.data = 12345  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        with pytest.raises(TypeError):
            transform.apply(item)
