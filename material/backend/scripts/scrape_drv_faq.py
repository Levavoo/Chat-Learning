#!/usr/bin/env python3
"""Scrape DRV Bund FAQ page into agent-search-index JSON."""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date
from pathlib import Path
from urllib.request import urlopen

from bs4 import BeautifulSoup, Tag
from bs4.element import PageElement

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://www.deutsche-rentenversicherung.de/SharedDocs/FAQ/A-und-B/faq-a-und-b.html"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "agent-search-index"
DOC_ID = "FAQ_DRV_Web"
SKIP_QUESTION = "Ihre Frage war nicht dabei?"


def _clean(text: str) -> str:
    """Remove soft hyphens, collapse whitespace, strip."""
    text = text.replace("\xad", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _process_element(el: Tag) -> list[str]:
    """Convert one HTML element into text lines."""
    if el.name in ("h2", "h3", "h4"):
        text = _clean(el.get_text())
        return [f"### {text}"] if text else []
    if el.name == "p":
        text = _clean(el.get_text())
        return [text] if text else []
    if el.name in ("ul", "ol"):
        items = []
        for li in el.find_all("li", recursive=False):
            text = _clean(li.get_text())
            if text:
                items.append(f"- {text}")
        return items
    if el.name == "table":
        rows = []
        for row in el.find_all("tr"):
            cells = [_clean(cell.get_text()) for cell in row.find_all(["td", "th"])]
            if any(cells):
                rows.append(" | ".join(cells))
        return rows
    if el.name == "div":
        return _extract_content(list(el.children)).split("\n") if _extract_content(list(el.children)) else []
    return []


def _extract_content(elements: list[PageElement]) -> str:
    """Convert a list of HTML elements between h2s into plain text."""
    parts: list[str] = []
    for el in elements:
        if not isinstance(el, Tag):
            continue
        parts.extend(_process_element(el))
    return "\n".join(parts)


def fetch_and_parse(url: str) -> list[dict[str, str]]:
    """Fetch the FAQ page and return the Q&A sections between the h1 and the contact box."""
    logger.info("Fetching %s", url)
    with urlopen(url) as resp:  # noqa: S310
        html = resp.read().decode("utf-8")

    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        logger.error("Could not find h1 on page")
        return []

    faq_questions = [
        "Wie ändert sich die Auszahlung",
        "Wann kann ich in Rente gehen",
        "Gibt es Möglichkeiten, zusätzlich Geld",
        "Wie beantrage ich meine Rente",
        "Wer kann mir weiterhelfen",
        "Ich habe meine Rentenzahlung nicht erhalten",
        "Wird mein Einkommen auf meine Rente angerechnet",
        "Welche Auswirkung hat es auf die gesetzliche Rentenversicherung",
        "Wie bekomme ich meine Renteninformation",
        "Ich bin selbstständig",
        "Ich bin krank",
    ]

    def _is_faq_question(text: str) -> bool:
        return any(text.startswith(q) for q in faq_questions)

    headings = h1.find_all_next("h2")

    sections: list[dict[str, str]] = []
    for h2 in headings:
        question = _clean(h2.get_text())
        if not question or not _is_faq_question(question):
            continue
        if SKIP_QUESTION in question:
            continue

        # Collect siblings until the next FAQ-level h2; keep non-FAQ h2s as ### sub-headings.
        content_elements: list[PageElement] = []
        for sibling in h2.next_siblings:
            if isinstance(sibling, Tag) and sibling.name == "h2":
                sibling_text = _clean(sibling.get_text())
                if _is_faq_question(sibling_text) or SKIP_QUESTION in sibling_text:
                    break
                content_elements.append(sibling)
            else:
                content_elements.append(sibling)

        content = _extract_content(content_elements)
        if content:
            sections.append({"title": question, "content": content})

    logger.info("Extracted %d FAQ sections", len(sections))
    return sections


def write_faq_document(sections: list[dict[str, str]], output_dir: Path) -> None:
    """Write FAQ_DRV_Web.json in Tier-2 format."""
    doc = {
        "doc_id": DOC_ID,
        "title": "Häufige Fragen aus der Beratung",
        "category": "FAQ",
        "edition": "Online",
        "published": date.today().isoformat(),
        "brochure_number": DOC_ID,
        "keywords": [
            "Rentenantrag",
            "Erwerbsminderungsrente",
            "Hinzuverdienst",
            "Altersrente",
            "Hinterbliebenenrente",
            "Selbstständige",
            "Rehabilitation",
            "Renteninformation",
            "Ausland",
            "freiwillige Beiträge",
        ],
        "summary": "Antworten auf die häufigsten Fragen zu Rentenantrag, Hinzuverdienst, "
        "Erwerbsminderung, Ausland, Selbstständigkeit und Online-Services.",
        "sections": sections,
    }

    docs_dir = output_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"{DOC_ID}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape DRV FAQ page into agent search index JSON")
    parser.add_argument("--url", default=DEFAULT_URL, help="FAQ page URL")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sections = fetch_and_parse(args.url)
    write_faq_document(sections, args.output_dir)
    logger.info("Done.")


if __name__ == "__main__":
    main()
