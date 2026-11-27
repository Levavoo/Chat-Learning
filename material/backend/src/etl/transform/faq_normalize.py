from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

import bs4


@dataclass(frozen=True)
class FaqItem:
    """One extracted FAQ accordion item before document selection."""

    question: str
    anchor_id: str | None
    content_html: str


@dataclass(frozen=True)
class FaqDocument:
    """A validated, document-bearing FAQ category."""

    question: str
    anchor_id: str
    content_html: str
    display_name: str


class GeneratedFaqDocument(TypedDict):
    """Manifest representation of one generated FAQ document."""

    item_name: str
    display_name: str
    anchor_id: str


# Canonical FAQ chunk-metadata contract (#700). Persisted to the sidecar so
# Bedrock vector retrieval and BM25 return identical metadata for the same S3
# key, enabling byte-identical semantic-header rollout.
FAQ_CHUNK_TYPE: str = "faq"
FAQ_CATEGORY: str = "FAQ"
REQUIRED_FAQ_METADATA_KEYS: frozenset[str] = frozenset({
    "chunk_type",
    "category",
    "name",
    "section_title",
    "title",
    "brochure_number",
    "brochure_url",
})


class FaqMetadataError(ValueError):
    """A generated FAQ document is missing required canonical metadata."""


AKTUELLES_IDENTITY = "aktuelles"
CONTACT_IDENTITY = "ihre frage war nicht dabei"

# Contact-boundary mode per source, keyed by stem (#987). ``required``: exactly
# one contact item, last, excluded. ``optional``: a contact item, if present,
# must be last and is excluded; without one every item is a document. Unknown
# stems fall back to ``required``, so a new source has to opt in here.
# Only the first div.c-accordion is read; for ``optional`` the fetch job in
# renate/scheduled-jobs guards the list end by requiring exactly one accordion
# per page (#999).
CONTACT_REQUIRED = "required"
CONTACT_OPTIONAL = "optional"
CONTACT_BOUNDARY_MODES: Mapping[str, str] = {
    "faq-a-und-b": CONTACT_REQUIRED,
    "faq-pflegeversicherung": CONTACT_OPTIONAL,
    "faq-fruehstartrente": CONTACT_OPTIONAL,
    "faq-rentenanpassung-2026": CONTACT_OPTIONAL,
    "faq-a1-bescheinigung": CONTACT_OPTIONAL,
    "faq-rentenanspruch-international": CONTACT_OPTIONAL,
}


def contact_boundary_mode(source_stem: str) -> str:
    """Return the contact-boundary mode for a source stem (``required`` unless opted in)."""
    return CONTACT_BOUNDARY_MODES.get(source_stem, CONTACT_REQUIRED)


# Keyed by normalized heading identity prefixes, never by position; unknown
# valid categories fall back to their source heading.
FAQ_DISPLAY_NAMES: tuple[tuple[str, str], ...] = (
    ("wann kann ich in rente gehen", "FAQ Rentenbeginn"),
    ("gibt es moglichkeiten zusatzlich geld", "FAQ Einzahlungen"),
    ("wie beantrage ich meine rente", "FAQ Antragstellung"),
    ("wer kann mir weiterhelfen", "FAQ Antrag oder Verfahren"),
    ("ich habe meine rentenzahlung nicht erhalten", "FAQ Rentenzahlung"),
    ("wird mein einkommen auf meine rente angerechnet", "FAQ Einkommensanrechnung"),
    (
        "welche auswirkung hat es auf die gesetzliche rentenversicherung",
        "FAQ Rentenversicherung und Ausland",
    ),
    ("wie bekomme ich meine renteninformation", "FAQ Versicherungskonto"),
    ("ich bin selbststandig", "FAQ Selbständigkeit"),
    ("ich bin krank", "FAQ Krankheit, Reha, Erwerbsminderung"),
    ("wie andert sich die auszahlung", "FAQ Rentenbeginn"),
)


def normalize_heading_identity(question: str) -> str:
    """Return a stable identity for boundary and display-name matching."""
    normalized = unicodedata.normalize("NFKD", question)
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = normalized.casefold()
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def _matches_identity(question: str, identity: str) -> bool:
    normalized = normalize_heading_identity(question)
    return normalized == identity or normalized.startswith(f"{identity} ")


def _resolve_display_name(item: FaqItem) -> str:
    identity = normalize_heading_identity(item.question)
    for prefix, display_name in FAQ_DISPLAY_NAMES:
        if identity == prefix or identity.startswith(f"{prefix} "):
            return display_name
    return item.question.strip()


def _required_boundary_index(items: list[FaqItem], identity: str, label: str) -> int:
    indexes = [index for index, item in enumerate(items) if _matches_identity(item.question, identity)]
    if len(indexes) != 1:
        raise ValueError(f"Expected exactly one {label} boundary, found {len(indexes)}")
    return indexes[0]


def _optional_boundary_index(items: list[FaqItem], identity: str, label: str) -> int | None:
    indexes = [index for index, item in enumerate(items) if _matches_identity(item.question, identity)]
    if len(indexes) > 1:
        raise ValueError(f"Expected at most one {label} boundary, found {len(indexes)}")
    return indexes[0] if indexes else None


def _document_from_item(item: FaqItem, seen_anchors: set[str]) -> FaqDocument:
    if not item.question.strip():
        raise ValueError("FAQ category has an empty heading")
    answer_text = bs4.BeautifulSoup(item.content_html, "html.parser").get_text(" ", strip=True)
    if not item.content_html.strip() or not answer_text:
        raise ValueError(f"FAQ category {item.question!r} has an empty answer")
    if not item.anchor_id:
        raise ValueError(f"FAQ category {item.question!r} has no anchor")
    if item.anchor_id in seen_anchors:
        raise ValueError(f"Duplicate FAQ anchor: {item.anchor_id}")
    seen_anchors.add(item.anchor_id)
    return FaqDocument(
        question=item.question.strip(),
        anchor_id=item.anchor_id,
        content_html=item.content_html,
        display_name=_resolve_display_name(item),
    )


def strip_page_chrome(raw_html: str | bytes) -> bytes:
    """Retain the FAQ accordion and ``dc.date`` while removing page chrome."""
    if isinstance(raw_html, bytes):
        raw_html = raw_html.decode("utf-8")

    soup = bs4.BeautifulSoup(raw_html, "html.parser")
    accordion = soup.find("div", class_="c-accordion")
    dc_date_tag = soup.find("meta", {"name": "dc.date"})

    head_parts = ['<meta charset="UTF-8">']
    if dc_date_tag:
        head_parts.append(str(dc_date_tag))

    return "\n".join([
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        *head_parts,
        "</head>",
        "<body>",
        str(accordion) if accordion else "",
        "</body>",
        "</html>",
    ]).encode("utf-8")


def _tag_has_class(tag: bs4.element.Tag | None, class_name: str) -> bool:
    if tag is None:
        return False
    classes = tag.get("class")
    if isinstance(classes, str):
        return classes == class_name
    return classes is not None and class_name in classes


def extract_faq_items(html_content: str | bytes) -> list[FaqItem]:
    """Extract every FAQ heading, including entries with a missing answer."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8")

    soup = bs4.BeautifulSoup(html_content, "html.parser")
    accordion = soup.find("div", class_="c-accordion")
    if not accordion:
        return []

    items: list[FaqItem] = []
    for heading in accordion.find_all("h2", class_="c-accordion__heading"):
        button = heading.find("button")
        question = (button or heading).get_text(" ", strip=True)

        anchor_id: str | None = None
        if button:
            anchor_id = str(button.get("aria-controls") or button.get("id") or "").strip() or None
        if not anchor_id:
            anchor_id = str(heading.get("id") or "").strip() or None

        candidate = accordion.find(id=anchor_id) if anchor_id else None
        content_div = candidate if isinstance(candidate, bs4.element.Tag) else None
        if not _tag_has_class(content_div, "c-accordion__content"):
            sibling = heading.find_next_sibling()
            immediate_sibling = sibling if isinstance(sibling, bs4.element.Tag) else None
            content_div = (
                immediate_sibling
                if immediate_sibling
                and immediate_sibling.name == "div"
                and _tag_has_class(immediate_sibling, "c-accordion__content")
                else None
            )
        if not anchor_id and content_div:
            anchor_id = str(content_div.get("id") or "").strip() or None
        content_html = content_div.decode_contents() if content_div else ""
        items.append(FaqItem(question=question, anchor_id=anchor_id, content_html=content_html))

    return items


def select_document_faq_items(items: list[FaqItem], *, source_stem: str) -> list[FaqDocument]:
    """Validate boundaries and return every document-bearing FAQ category."""
    if not items:
        raise ValueError("No FAQ accordion items found")

    aktuelles_index = _optional_boundary_index(items, AKTUELLES_IDENTITY, "Aktuelles")
    if contact_boundary_mode(source_stem) == CONTACT_OPTIONAL:
        contact_index = _optional_boundary_index(items, CONTACT_IDENTITY, "contact")
    else:
        contact_index = _required_boundary_index(items, CONTACT_IDENTITY, "contact")
    if aktuelles_index is not None and aktuelles_index != 0:
        raise ValueError("Aktuelles boundary must be the first FAQ item")
    if contact_index is not None and contact_index != len(items) - 1:
        raise ValueError("Contact boundary must be the last FAQ item")

    start = 1 if aktuelles_index == 0 else 0
    end = len(items) - 1 if contact_index is not None else len(items)
    document_items = items[start:end]
    if not document_items:
        raise ValueError("FAQ must contain at least one document-bearing category")

    seen_anchors: set[str] = set()
    return [_document_from_item(item, seen_anchors) for item in document_items]


def extract_publish_date(html_content: str | bytes) -> str | None:
    """Extract the ``dc.date`` value, when present."""
    if isinstance(html_content, bytes):
        html_content = html_content.decode("utf-8")
    soup = bs4.BeautifulSoup(html_content, "html.parser")
    tag = soup.find("meta", {"name": "dc.date"})
    return str(tag.get("content")) if tag and tag.get("content") is not None else None


def _canonical_document_payload(document: FaqDocument) -> dict[str, str]:
    return {
        "anchor_id": document.anchor_id,
        "content_html": re.sub(r"\s+", " ", document.content_html).strip(),
        "display_name": document.display_name,
        "question": re.sub(r"\s+", " ", document.question).strip(),
    }


def semantic_faq_hash(html_content: str | bytes, *, source_stem: str) -> str:
    """Hash canonical JSON for all validated document-bearing categories."""
    documents = select_document_faq_items(extract_faq_items(html_content), source_stem=source_stem)
    canonical_json = json.dumps(
        [_canonical_document_payload(document) for document in documents],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()


def generated_faq_documents(html_content: str | bytes, source_stem: str) -> list[GeneratedFaqDocument]:
    """Return the complete ordered generated-document contract for a manifest."""
    documents = select_document_faq_items(extract_faq_items(html_content), source_stem=source_stem)
    return [
        GeneratedFaqDocument(
            item_name=f"{source_stem}/{source_stem}_{index:04d}",
            display_name=document.display_name,
            anchor_id=document.anchor_id,
        )
        for index, document in enumerate(documents)
    ]


def build_faq_metadata(document: FaqDocument, *, brochure_number: str, brochure_url_base: str | None) -> dict[str, str]:
    """Return sidecar-ready canonical metadata for one FAQ document."""
    # Anchor is appended here so runtime producer and CI publication gate build
    # the URL identically. brochure_url omitted when base is falsy → fails closed.
    metadata: dict[str, str] = {
        "chunk_type": FAQ_CHUNK_TYPE,
        "category": FAQ_CATEGORY,
        "name": document.display_name,
        "section_title": document.question,
        "title": f"FAQ — {document.question}",
        "brochure_number": brochure_number,
    }
    if brochure_url_base:
        metadata["brochure_url"] = f"{brochure_url_base}#{document.anchor_id}"
    return metadata


def validate_faq_metadata(metadata: Mapping[str, object]) -> None:
    """Raise :class:`FaqMetadataError` if any required key is missing or empty."""
    missing = sorted(key for key in REQUIRED_FAQ_METADATA_KEYS if not str(metadata.get(key) or "").strip())
    if missing:
        raise FaqMetadataError(f"FAQ metadata is missing required keys: {', '.join(missing)}")


def validate_generated_faq_metadata(html_content: str | bytes, source_stem: str, brochure_url_base: str | None) -> None:
    """Build and validate metadata for every document-bearing category."""
    # Fails closed on the first document whose canonical metadata is incomplete.
    for document in select_document_faq_items(extract_faq_items(html_content), source_stem=source_stem):
        metadata = build_faq_metadata(document, brochure_number=source_stem, brochure_url_base=brochure_url_base)
        validate_faq_metadata(metadata)
