import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar

import yaml

from etl.models import DataType, PipelineItem
from etl.transform.base import Transform
from etl.util.logging_setup import get_logger

_BROCHURE_URLS_PATH = Path(__file__).parent.parent / "config" / "brochure_urls.yaml"
logger = get_logger(__name__)


def load_brochure_url_mapping(path: Path | None = None) -> dict[str, str]:
    """Load brochure number -> URL mapping from YAML config."""
    if path is None:
        path = _BROCHURE_URLS_PATH
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError as e:
        logger.warning(f"Malformed YAML in brochure URL mapping file {path}: {e}")
        return {}


class extract_metadata_from_dita(Transform):
    r"""Transform that extracts metadata from a DITA XML into the PipelineItem's metadata.

    input_types: XmlType (.xml)
    output_types: XmlType (.xml)
    name: ``META_FROM_DITA``
    """

    output_type = DataType.XML
    supported_input_types: ClassVar[list[DataType]] = [DataType.XML]
    transform_type = "META_FROM_DITA"

    logger = get_logger("META_FROM_DITA")

    def __init__(self, brochure_url_mapping: dict[str, str] | None = None) -> None:
        super().__init__()
        self.brochure_url_mapping = (
            brochure_url_mapping if brochure_url_mapping is not None else load_brochure_url_mapping()
        )

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        """Extract metadata from DITA XML."""
        metadata = {}
        self.logger.info("Extracting Metadata from DITA XML.")

        if isinstance(item.data_object.data, bytes):
            data = item.data_object.data.decode(encoding="UTF-8")
        else:
            data = item.data_object.data

        root = ET.fromstring(data)

        if root.tag != "topic":
            self.logger.warning("No Metadata found in XML.")
            return [item]

        self._extract_title(root, metadata)

        prolog_el = root.find("prolog")
        if prolog_el is None:
            self.logger.warning("No <prolog> found in XML.")
            return [item]

        self._extract_prolog_metadata(prolog_el, metadata)
        self._log_brochure_number(metadata)
        self._resolve_brochure_url(metadata)

        metadata_summary = {
            "name": metadata.get("name", "N/A")[:50],
            "brochure_number": metadata.get("brochure_number", "N/A"),
            "brochure_url": metadata.get("brochure_url", "N/A")[:80] if metadata.get("brochure_url") else "N/A",
            "category": metadata.get("category", "N/A"),
            "total_fields": len(metadata),
        }
        self.logger.info(f"Metadata extraction complete: {metadata_summary}")

        data_obj = item.data_object
        data_obj.metadata = metadata

        return [item.model_copy(update={"data_object": data_obj})]

    def _extract_title(self, root: ET.Element, metadata: dict) -> None:
        """Extract title (including text from nested inline elements) into metadata['name']."""
        title = root.find("title")
        if title is None:
            self.logger.debug("No title element found")
            return
        title_text = "".join(title.itertext()).strip()
        if not title_text:
            self.logger.debug("Title element found but no text extracted")
            return
        metadata["name"] = title_text
        suffix = "..." if len(title_text) > 100 else ""
        self.logger.info(f"Extracted title: {title_text[:100]}{suffix}")

    def _extract_prolog_metadata(self, prolog_el: ET.Element, metadata: dict) -> None:
        """Pull category, keywords, and <data>/<othermeta> fields out of <prolog>.

        Explicit <metadata><category> always wins; otherwise ``<data name="rubrik">``
        is promoted to category. The raw ``rubrik`` key is dropped from the output.
        """
        metadata_el = prolog_el.find("metadata")
        if metadata_el is None:
            self.logger.debug("No <metadata> element under <prolog>; continuing with <data> fields only.")
        else:
            category = self._get_category(metadata_el)
            if category:
                metadata["category"] = category

            keywords, primary_keywords = self._get_keywords(metadata_el)
            if keywords:
                metadata["keywords"] = keywords
            if primary_keywords:
                metadata["primary_keywords"] = primary_keywords

        metadata.update(self._get_data_fields(prolog_el))
        metadata.update(self._get_othermeta_fields(prolog_el))

        rubrik = metadata.pop("rubrik", None)
        if rubrik and "category" not in metadata:
            metadata["category"] = rubrik

    def _log_brochure_number(self, metadata: dict) -> None:
        """Log the brochure_number lookup key (or fallback to title)."""
        brochure_number = metadata.get("brochure_number")
        if brochure_number:
            self.logger.info(f"Extracted brochure_number: {brochure_number}")
        else:
            self.logger.info(
                f"No brochure_number found, using name for URL resolution as fallback: {metadata.get('name')}"
            )

    def _get_category(self, metadata_element: ET.Element) -> str | None:
        """Get the category from the metadata safely."""
        cat_el = metadata_element.find("category")
        if cat_el is None:
            return None
        if not cat_el.text:
            return None
        return cat_el.text.strip()

    def _get_keywords(self, metadata_element: ET.Element) -> tuple[str | None, str | None]:
        """Return (all keywords, primary keywords) as comma-separated strings.

        Primary keywords are tagged with ``otherprops="hauptstichwort"``.
        """
        keywords_el = metadata_element.find("keywords")
        if keywords_el is None:
            return None, None

        keywords: list[str] = []
        primary: list[str] = []
        for keyword in keywords_el:
            if keyword.tag != "keyword" or not keyword.text:
                continue
            text = keyword.text.strip()
            keywords.append(text)
            if keyword.get("otherprops") == "hauptstichwort":
                primary.append(text)

        return (
            ", ".join(keywords) if keywords else None,
            ", ".join(primary) if primary else None,
        )

    def _get_data_fields(self, prolog_tag: ET.Element) -> dict[str, str]:
        """Return ``<data>`` fields with mapped names."""
        field_map = self._data_field_map()
        metadata = {}
        for data in prolog_tag.findall("data"):
            name = data.get("name")
            value = data.get("value", "").strip()
            if name and value:
                mapped_name = field_map.get(name, name)
                metadata[mapped_name] = value
        return metadata

    def _resolve_brochure_url(self, metadata: dict) -> None:
        """Look up brochure URL from mapping and add to metadata.

        Trusts a ``<data name="websitelink">`` URL already in metadata over the YAML lookup.
        """
        if metadata.get("brochure_url"):
            self.logger.info(f"brochure_url already set from XML: {metadata['brochure_url'][:80]}...")
            return

        brochure_url = metadata.get("brochure_number")
        if "brochure_number" not in metadata:
            self.logger.debug("No brochure_number; falling back to name for URL resolution.")
            brochure_url = metadata.get("name")
            if "name" not in metadata:
                self.logger.debug("No name found in metadata to resolve brochure_url")
                return

        url = None
        if isinstance(brochure_url, str):
            # Exact match first, then normalized (no spaces) for "FB 28" vs "FB28".
            url = self.brochure_url_mapping.get(brochure_url) or self.brochure_url_mapping.get(
                brochure_url.replace(" ", "")
            )
        if url:
            metadata["brochure_url"] = url
            self.logger.info(f"Resolved brochure_url for {brochure_url}: {url[:80]}...")
        else:
            self.logger.warning(f"No URL mapping found for brochure: {brochure_url}")

    def _get_othermeta_fields(self, prolog_tag: ET.Element) -> dict[str, str]:
        """Return ``<othermeta>`` fields with optional name mapping."""
        field_map = self._data_field_map()
        metadata = {}
        for othermeta in prolog_tag.findall("metadata/othermeta"):
            name = othermeta.get("name")
            content = othermeta.get("content", "").strip()
            if name and content:
                mapped_name = field_map.get(name, name)
                metadata[mapped_name] = content
        return metadata

    @staticmethod
    def _data_field_map() -> dict[str, str]:
        """Field name mapping for <data> and <othermeta>; covers old and new schema names."""
        return {
            "broschrennummer": "brochure_number",
            "veroeffentlichung": "publishing_date",
            "broschuerennummer": "brochure_number",
            "veroeffentlichungsdatum": "publishing_date",
            "rubrik": "rubrik",
            "kurztitel": "short_title",
            "sprache": "language",
            "websitelink": "brochure_url",
            "auflage": "edition",
        }
