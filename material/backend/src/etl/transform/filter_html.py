import html
import os
from typing import ClassVar

import bs4

from etl.models import DataObject, DataType, PipelineItem
from etl.transform.base import Transform
from etl.transform.extract_metadata import load_brochure_url_mapping
from etl.transform.faq_normalize import (
    build_faq_metadata,
    extract_faq_items,
    extract_publish_date,
    select_document_faq_items,
    validate_faq_metadata,
)
from etl.util.logging_setup import get_logger


class prepare_faq_html(Transform):
    """Transform that splits an FAQ page into one PipelineItem per question.

    Each FAQ question+answer pair becomes an independent HTML document so that
    TEXT2MD can produce one Markdown chunk per question, improving KB retrieval
    precision by keeping semantic boundaries at the individual Q&A level.

    The optional first "Aktuelles" boundary and the final
    "Ihre Frage war nicht dabei?" boundary (required or optional per source
    stem, see ``faq_normalize.CONTACT_BOUNDARY_MODES``) are identified by
    question text prefix and skipped. Display names are assigned semantically
    (by matching question text), not positionally.
    """

    supported_input_types: ClassVar[list[DataType]] = [DataType.HTML]
    output_type = DataType.HTML

    transform_type = "PrepareFAQHTML"

    def __init__(self) -> None:
        self.logger = get_logger("PrepareFAQHTML")
        self.brochure_url_mapping = load_brochure_url_mapping()

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        """Split one FAQ page into one PipelineItem per document-bearing question."""
        self.logger.debug("Preparing FAQ HTML content")

        if isinstance(item.data_object.data, bytes):
            data = item.data_object.data.decode("UTF-8")
        elif isinstance(item.data_object.data, str):
            data = item.data_object.data
        else:
            raise TypeError("Unsupported data type for HTML content.")

        base_name = os.path.splitext(item.name)[0]
        base_url = self.brochure_url_mapping.get(f"{base_name}.md") or self.brochure_url_mapping.get(item.name)
        if not base_url:
            self.logger.warning(f"No URL mapping found for FAQ: {base_name}.md")

        publish_date = extract_publish_date(data)

        doc_items = select_document_faq_items(extract_faq_items(data), source_stem=base_name)

        output_items = []
        for chunk_index, faq_item in enumerate(doc_items):
            # Heading downgrade + attr-strip are non-idempotent; apply exactly once per item.
            content_html = self._clean_content_html(faq_item.content_html)

            chunk_name = f"{base_name}/{base_name}_{chunk_index:04d}"

            # Validation fails closed so a missing URL mapping surfaces via DLQ
            # rather than a silently incomplete sidecar (#700).
            metadata = build_faq_metadata(faq_item, brochure_number=base_name, brochure_url_base=base_url)
            validate_faq_metadata(metadata)
            if metadata.get("brochure_url"):
                self.logger.debug(
                    f"Resolved brochure_url for {faq_item.display_name}: {metadata['brochure_url'][:80]}..."
                )

            new_data_object = DataObject(
                name=chunk_name,
                data=self._build_faq_html(faq_item.question, content_html, publish_date),
                data_type=DataType.HTML,
                metadata=metadata,
            )
            output_items.append(item.model_copy(update={"data_object": new_data_object, "name": chunk_name}))

        self.logger.info(f"Split {item.name} into {len(output_items)} FAQ chunks")
        return output_items

    def _clean_content_html(self, content_html: str) -> str:
        # Non-idempotent: must be applied exactly once per item.
        soup = bs4.BeautifulSoup(content_html, "html.parser")
        self._downgrade_headings(soup)
        for tag in soup.find_all(True):
            attrs_to_keep = ["href", "title"]
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in attrs_to_keep}
        return soup.decode_contents()

    def _build_faq_html(self, question: str, content_html: str, publish_date: str | None) -> str:
        head_parts = ['<meta charset="UTF-8">', f"<title>{html.escape(question)}</title>"]
        if publish_date:
            head_parts.append(f'<meta name="date_of_publish" content="{html.escape(publish_date)}">')
        parts = [
            "<!DOCTYPE html>",
            "<html>",
            "<head>",
            *head_parts,
            "</head>",
            "<body>",
            f"<h1>{html.escape(question)}</h1>",
            content_html,
            "</body>",
            "</html>",
        ]
        return "\n".join(parts)

    def _downgrade_headings(self, element: bs4.element.Tag) -> None:
        for header_level in range(6, 0, -1):
            downgraded_level = min(header_level + 1, 6)
            for tag in element.find_all(f"h{header_level}"):
                tag.name = f"h{downgraded_level}"
