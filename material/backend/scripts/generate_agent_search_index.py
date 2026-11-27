#!/usr/bin/env python3
"""Generate two-tier JSON search index from DITA XML brochures."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "xml"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "agent-search-index"

_BROCHURE_ID_RE = re.compile(r"^[A-Z]{1,2}\d{2,4}$")
_SHORT_URL_BASE = "https://www.deutsche-rentenversicherung.de"


def _derive_short_brochure_url(brochure_id: str) -> str | None:
    """Derive the short-form public URL for a brochure ID, or None if not derivable."""
    if not _BROCHURE_ID_RE.match(brochure_id):
        return None
    return f"{_SHORT_URL_BASE}/{brochure_id}"


def _clean_text(text: str) -> str:
    """Remove soft hyphens, collapse whitespace, strip."""
    text = text.replace("\xad", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_text(element: ET.Element) -> str:
    """Recursively extract all text from an element, stripping tags."""
    return "".join(element.itertext())


def _process_list(child: ET.Element, ordered: bool) -> list[str]:
    """Extract list items from a <ul> or <ol> element."""
    parts: list[str] = []
    for i, li in enumerate(child.findall("li"), 1):
        text = _clean_text(_extract_text(li))
        if text:
            parts.append(f"{i}. {text}" if ordered else f"- {text}")
    return parts


def _process_note(child: ET.Element) -> str | None:
    """Extract note content prefixed with 'Hinweis: '."""
    note_texts = [_clean_text(_extract_text(p)) for p in child.findall("p")]
    note_texts = [t for t in note_texts if t]
    return ("Hinweis: " + " ".join(note_texts)) if note_texts else None


def _process_table(child: ET.Element) -> list[str]:
    """Extract table rows as pipe-separated text."""
    parts: list[str] = []
    for row in child.iter("row"):
        cells = [c for c in (_clean_text(_extract_text(e)) for e in row.findall("entry")) if c]
        if cells:
            parts.append(" | ".join(cells))
    return parts


def _process_div(div: ET.Element) -> list[str]:
    """Extract content from a <div> element, including its <wintitle> as sub-heading."""
    parts: list[str] = []
    for child in div:
        tag = child.tag
        if tag == "wintitle":
            text = _clean_text(_extract_text(child))
            if text:
                parts.append(f"### {text}")
        elif tag == "p":
            text = _clean_text(_extract_text(child))
            if text:
                parts.append(text)
        elif tag in ("ul", "ol"):
            parts.extend(_process_list(child, ordered=(tag == "ol")))
        elif tag == "note":
            note = _process_note(child)
            if note:
                parts.append(note)
        elif tag == "table":
            parts.extend(_process_table(child))
    return parts


def _element_to_parts(child: ET.Element) -> list[str]:
    """Convert a single XML element to text parts."""
    tag = child.tag
    if tag == "p":
        text = _clean_text(_extract_text(child))
        return [text] if text else []
    elif tag in ("ul", "ol"):
        return _process_list(child, ordered=(tag == "ol"))
    elif tag == "note":
        note = _process_note(child)
        return [note] if note else []
    elif tag == "table":
        return _process_table(child)
    elif tag == "div":
        return _process_div(child)
    return []


def _extract_section_content(section: ET.Element) -> str:
    """Extract clean text content from a section element (flat, no sub-splitting)."""
    parts: list[str] = []
    for child in section:
        if child.tag == "title":
            continue
        parts.extend(_element_to_parts(child))
    return "\n".join(parts)


def _extract_subsections(section: ET.Element, parent_title: str) -> list[dict[str, str]]:
    """Extract sub-sections from a section element, splitting on <div> with <wintitle>.

    If the section contains divs with wintitles, each becomes its own section.
    Content before the first titled div is grouped under the parent title.
    If no titled divs exist, returns a single section with all content.
    """
    # Check if any div has a wintitle
    has_titled_divs = any(child.tag == "div" and child.find("wintitle") is not None for child in section)

    if not has_titled_divs:
        content = _extract_section_content(section)
        return [{"title": parent_title, "content": content}]

    # Split: preamble + individual divs
    subsections: list[dict[str, str]] = []
    preamble_parts: list[str] = []

    for child in section:
        if child.tag == "title":
            continue
        if child.tag == "div" and child.find("wintitle") is not None:
            # Flush preamble if any
            if preamble_parts:
                subsections.append({"title": parent_title, "content": "\n".join(preamble_parts)})
                preamble_parts = []
            # This div becomes its own section
            wintitle_el = child.find("wintitle")
            div_title = _clean_text(_extract_text(wintitle_el)) if wintitle_el is not None else ""
            div_parts = _process_div(child)
            div_content = "\n".join(p for p in div_parts if not p.startswith("### "))
            full_title = f"{parent_title} - {div_title}" if div_title else parent_title
            subsections.append({"title": full_title, "content": div_content})
        else:
            preamble_parts.extend(_element_to_parts(child))

    # Flush remaining preamble
    if preamble_parts:
        subsections.append({"title": parent_title, "content": "\n".join(preamble_parts)})

    return subsections


def _get_data_value(root: ET.Element, name: str) -> str:
    """Return the value attribute from a ``<data name='...'>`` element."""
    for data in root.iter("data"):
        if data.get("name") == name:
            return data.get("value", "")
    return ""


def parse_xml(filepath: Path) -> dict:
    """Parse a single DITA XML file into a structured dict."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    title_el = root.find("title")
    title = _clean_text(_extract_text(title_el)) if title_el is not None else ""

    category_el = next(root.iter("category"), None)
    category = _clean_text(category_el.text) if category_el is not None and category_el.text else ""

    keywords = []
    for kw in root.iter("keyword"):
        if kw.text and kw.text.strip():
            keywords.append(kw.text.strip())

    doc_id = _get_data_value(root, "broschrennummer").strip().replace(" ", "")
    edition = _get_data_value(root, "auflage").strip()
    published = _get_data_value(root, "veroeffentlichung").strip()

    sections: list[dict[str, str]] = []
    for section in root.iter("section"):
        title_el = section.find("title")
        section_title = _clean_text(_extract_text(title_el)) if title_el is not None else ""

        # Skip untitled TOC-only sections (bare ``<ul>`` children).
        if not section_title:
            children_tags = {child.tag for child in section}
            if children_tags <= {"ul"}:
                continue

        subsections = _extract_subsections(section, section_title)
        sections.extend(subsections)

    sections = _split_large_sections(sections)

    return {
        "doc_id": doc_id,
        "title": title,
        "category": category,
        "edition": edition,
        "published": published,
        "keywords": keywords,
        "sections": sections,
        "source_file": filepath.name,
    }


def parse_all_xml(input_dir: Path) -> list[dict]:
    """Parse all XML files and handle duplicate doc_ids."""
    xml_files = sorted(input_dir.glob("*.xml"))
    if not xml_files:
        raise FileNotFoundError(f"No XML files found in {input_dir}")

    docs: list[dict] = []
    seen_ids: dict[str, int] = {}

    for filepath in xml_files:
        try:
            doc = parse_xml(filepath)
        except ET.ParseError:
            logger.exception("Failed to parse %s", filepath.name)
            continue

        did = doc["doc_id"]
        if did in seen_ids:
            seen_ids[did] += 1
            doc["doc_id"] = f"{did}_v{seen_ids[did]}"
            logger.warning("Duplicate doc_id '%s' in %s, renamed to '%s'", did, filepath.name, doc["doc_id"])
        else:
            seen_ids[did] = 1

        docs.append(doc)

    logger.info("Parsed %d XML files", len(docs))
    return docs


def _invoke_bedrock(client, model_id: str, prompt: str, max_tokens: int = 4096) -> str:
    """Call Bedrock converse API and return the text response."""
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.1},
    )
    return response["output"]["message"]["content"][0]["text"]


def generate_missing_keywords(client, model_id: str, docs: list[dict]) -> None:
    """Generate keywords for documents that have none."""
    docs_needing_keywords = [d for d in docs if not d["keywords"]]
    if not docs_needing_keywords:
        logger.info("All documents have keywords, skipping generation")
        return

    logger.info("Generating keywords for %d documents", len(docs_needing_keywords))

    for doc in docs_needing_keywords:
        section_previews = [f"- {s['title']}: {s['content'][:200]}" for s in doc["sections"]]

        prompt = f"""Analysiere diese DRV-Broschüre und generiere 5-10 präzise Suchbegriffe (Keywords).
Die Keywords sollen spezifisch für dieses Dokument sein, nicht allgemein "Rente" oder "Deutsche Rentenversicherung".

Titel: {doc["title"]}
Kategorie: {doc["category"]}
Abschnitte:
{chr(10).join(section_previews)}

Antworte NUR mit einer JSON-Liste von Strings, z.B.: ["Keyword1", "Keyword2", "Keyword3"]"""

        try:
            result = _invoke_bedrock(client, model_id, prompt, max_tokens=512)
            match = re.search(r"\[.*\]", result, re.DOTALL)
            if match:
                doc["keywords"] = json.loads(match.group())
                logger.info("Generated %d keywords for %s", len(doc["keywords"]), doc["doc_id"])
            else:
                logger.warning("Could not parse keywords for %s: %s", doc["doc_id"], result[:100])
        except Exception:
            logger.exception("Failed to generate keywords for %s", doc["doc_id"])


def generate_summaries(client, model_id: str, docs: list[dict]) -> None:
    """Generate distinguishing summaries for all documents in a batch."""
    logger.info("Generating summaries for %d documents", len(docs))

    doc_overviews = []
    for doc in docs:
        section_titles = ", ".join(s["title"] for s in doc["sections"])
        keywords = ", ".join(doc["keywords"][:5]) if doc["keywords"] else "(keine)"
        doc_overviews.append(
            f'- {doc["doc_id"]}: "{doc["title"]}" | Kategorie: {doc["category"]} | '
            f"Keywords: {keywords} | Abschnitte: {section_titles}"
        )

    corpus = "\n".join(doc_overviews)

    prompt = f"""Du siehst eine Liste von {len(docs)} DRV-Broschüren zum deutschen Rentensystem.
Erstelle für JEDE Broschüre eine kurze Zusammenfassung (1-2 Sätze, max 30 Wörter).

WICHTIG: Die Zusammenfassung muss erklären, was DIESES Dokument von den anderen 53 unterscheidet.
SCHLECHT: "Informationen zur Rente" (zu allgemein)
GUT: "Rentenformel, Entgeltpunkte, Zugangsfaktor und Rentenanpassung für Westdeutschland."

Broschüren:
{corpus}

Antworte als JSON-Objekt mit doc_id als Key und Summary als Value:
{{"B06": "Rentenformel, Entgeltpunkte...", "F04": "..."}}"""

    try:
        result = _invoke_bedrock(client, model_id, prompt, max_tokens=8192)
        match = re.search(r"\{.*\}", result, re.DOTALL)
        if not match:
            logger.error("Could not parse summaries response: %s", result[:200])
            return

        summaries = json.loads(match.group())
        applied = 0
        for doc in docs:
            if doc["doc_id"] in summaries:
                doc["summary"] = summaries[doc["doc_id"]]
                applied += 1
            else:
                logger.warning("No summary generated for %s", doc["doc_id"])
                doc["summary"] = ""

        logger.info("Applied summaries to %d/%d documents", applied, len(docs))

    except Exception:
        logger.exception("Failed to generate summaries")
        for doc in docs:
            doc.setdefault("summary", "")


MAX_SECTION_CHARS = 3000


def _split_large_sections(sections: list[dict[str, str]]) -> list[dict[str, str]]:
    """Split sections exceeding MAX_SECTION_CHARS on paragraph boundaries."""
    result: list[dict[str, str]] = []
    for section in sections:
        content = section["content"]
        if len(content) <= MAX_SECTION_CHARS:
            result.append(section)
            continue

        paragraphs = content.split("\n")
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 1 > MAX_SECTION_CHARS and current:
                chunks.append("\n".join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para) + 1

        if current:
            chunks.append("\n".join(current))

        if len(chunks) == 1:
            result.append(section)
        else:
            for i, chunk in enumerate(chunks, 1):
                result.append({"title": f"{section['title']} (Teil {i})", "content": chunk})

    return result


def write_index(docs: list[dict], output_dir: Path) -> None:
    """Write the Tier 1 global index, including any extra per-doc JSON files not from XML."""
    docs_dir = output_dir / "documents"
    xml_doc_ids = {d["doc_id"] for d in docs}
    extra_docs: list[dict] = []

    if docs_dir.exists():
        for path in sorted(docs_dir.glob("*.json")):
            try:
                extra = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if extra.get("doc_id") not in xml_doc_ids:
                extra_docs.append(extra)
                logger.info("Including extra document in index: %s", extra.get("doc_id"))

    index_entries = [
        {
            "doc_id": d["doc_id"],
            "title": d["title"],
            "category": d["category"],
            "edition": d["edition"],
            "published": d["published"],
            "keywords": d["keywords"],
            "sections": [s["title"] for s in d["sections"]],
            "summary": d.get("summary", ""),
            "brochure_url_short": _derive_short_brochure_url(d["doc_id"]) or "",
        }
        for d in docs
    ]

    for extra in extra_docs:
        index_entries.append({
            "doc_id": extra["doc_id"],
            "title": extra["title"],
            "category": extra.get("category", ""),
            "edition": extra.get("edition", ""),
            "published": extra.get("published", ""),
            "keywords": extra.get("keywords", []),
            "sections": [s["title"] for s in extra.get("sections", [])],
            "summary": extra.get("summary", ""),
            "brochure_url_short": extra.get("brochure_url_short", ""),
        })

    index = {"documents": index_entries}
    path = output_dir / "index.json"
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%d documents)", path, len(index_entries))


def write_documents(docs: list[dict], output_dir: Path) -> None:
    """Write per-document Tier 2 files."""
    docs_dir = output_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    for doc in docs:
        short_url = _derive_short_brochure_url(doc["doc_id"])
        if not short_url:
            logger.warning("Could not derive Kurzlink for doc_id '%s'", doc["doc_id"])

        out = {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "category": doc["category"],
            "edition": doc["edition"],
            "published": doc["published"],
            "brochure_number": doc["doc_id"],
            "brochure_url_short": short_url or "",
            "sections": doc["sections"],
        }

        path = docs_dir / f"{doc['doc_id']}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    logger.info("Wrote %d document files to %s", len(docs), docs_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate agent search index from DITA XML")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM enrichment (keywords/summaries)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    docs = parse_all_xml(args.input_dir)

    if not args.skip_llm:
        import boto3

        model_id = os.environ.get("INDEX_GEN_MODEL_ID", "eu.amazon.nova-pro-v1:0")
        region = os.environ.get("AWS_REGION", "eu-central-1")
        client = boto3.client("bedrock-runtime", region_name=region)

        generate_missing_keywords(client, model_id, docs)
        generate_summaries(client, model_id, docs)
    else:
        logger.info("Skipping LLM enrichment (--skip-llm)")
        for doc in docs:
            doc.setdefault("summary", "")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_index(docs, args.output_dir)
    write_documents(docs, args.output_dir)

    logger.info("Done. Output: %s", args.output_dir)


if __name__ == "__main__":
    main()
