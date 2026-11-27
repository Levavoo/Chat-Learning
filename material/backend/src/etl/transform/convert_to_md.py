from io import BytesIO
from typing import ClassVar

from markitdown_no_magika import MarkItDown

from etl.models import DataType, PipelineItem
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger


class text_to_md(Transform):
    r"""Transform that converts text to Markdown using MarkItDown.

    Emits clean Markdown only: no YAML frontmatter is prepended to the body.
    Custom metadata travels solely in the ``.metadata.json`` sidecar, which the
    output repositories write from ``item.data_object.metadata`` independently of
    the body. Keeping metadata out of the body makes the bytes Bedrock embeds and
    BM25 returns identical to the stored ``.md`` for a given key (#696).

    The converted Markdown is ``.strip()``-ed so every path is leading/trailing
    whitespace-free — the FAQ path has no downstream ``CHUNK_MARKDOWN`` strip, and
    a chunk beginning with ``\n(`` is mis-sniffed by Bedrock's Tika content-type
    detector and silently dropped.

    input_type:
        DataType.XML, DataType.TEXT, DataType.HTML, DataType.PDF
    output_type:
        DataType.MARKDOWN
    name:
        \"TEXT2MD\"
    """

    output_type = DataType.MARKDOWN
    supported_input_types: ClassVar[list[DataType]] = [DataType.XML, DataType.TEXT, DataType.HTML, DataType.PDF]
    transform_type = "TEXT2MD"

    logger = get_logger("TEXT2MD")

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        self.logger.debug(f"Converting {item.data_object.data_type.value} to MARKDOWN")

        if isinstance(item.data_object.data, str):
            data = BytesIO(item.data_object.data.encode("UTF-8"))
        elif isinstance(item.data_object.data, bytes):
            data = BytesIO(item.data_object.data)
        else:
            raise TypeError(f"Input data must be str or bytes, got {type(item.data_object.data).__name__}")

        md = MarkItDown()
        converted = md.convert_stream(data, file_extension=item.data_object.data_type.value).markdown

        data_object = item.data_object
        data_object.data_type = DataType.MARKDOWN
        data_object.data = converted.strip()
        return [item.model_copy(update={"data_object": data_object})]
