#!/usr/bin/env python3
"""Extract structured text from Merkblätter PDFs using Amazon Textract."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from etl.util.merkblatt_markdown import render_sections_to_markdown
from scripts.generate_agent_search_index import generate_missing_keywords, generate_summaries

logger = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "pdfs"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "agent-search-index"
# Structured Merkblatt Markdown ships to the KB through the versioned releases/ path.
DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "source"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "pdfs" / "textract-cache"
DEFAULT_BUCKET = "renate-assets-dev-eu-central-1"
S3_PREFIX = "tmp/textract-merkblaetter"

_BROCHURE_ID_RE = re.compile(r"^[A-Z]{1,2}\d{2,4}$")
_SHORT_URL_BASE = "https://www.deutsche-rentenversicherung.de"


def _derive_short_brochure_url(brochure_id: str) -> str | None:
    """Derive the short-form public URL for a brochure ID, or None if not derivable."""
    if not _BROCHURE_ID_RE.match(brochure_id):
        return None
    return f"{_SHORT_URL_BASE}/{brochure_id}"


def _run_textract(pdf_path: Path, bucket: str, region: str) -> list[dict]:
    """Upload PDF to S3, run Textract async analysis, return blocks."""
    import boto3

    s3 = boto3.client("s3", region_name=region)
    textract = boto3.client("textract", region_name=region)

    key = f"{S3_PREFIX}/{pdf_path.name}"
    s3.upload_file(str(pdf_path), bucket, key)
    logger.info("Uploaded %s to s3://%s/%s", pdf_path.name, bucket, key)

    response = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["LAYOUT", "TABLES"],
    )
    job_id = response["JobId"]
    logger.info("Textract job started: %s", job_id[:16])

    while True:
        result = textract.get_document_analysis(JobId=job_id)
        status = result["JobStatus"]
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(f"Textract failed for {pdf_path.name}: {result.get('StatusMessage', 'unknown')}")
        time.sleep(2)

    blocks = result["Blocks"]
    next_token = result.get("NextToken")
    while next_token:
        result = textract.get_document_analysis(JobId=job_id, NextToken=next_token)
        blocks.extend(result["Blocks"])
        next_token = result.get("NextToken")

    s3.delete_object(Bucket=bucket, Key=key)
    pages = result.get("DocumentMetadata", {}).get("Pages", 0)
    logger.info("Extracted %d blocks from %s (%d pages)", len(blocks), pdf_path.name, pages)
    return blocks


def _get_textract_blocks(pdf_path: Path, cache_dir: Path, bucket: str, region: str, *, skip: bool) -> list[dict]:
    """Return Textract blocks from cache or by running Textract."""
    pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()[:16]
    cache_file = cache_dir / f"{pdf_path.stem}-{pdf_hash}.json"

    if skip:
        if not cache_file.exists():
            raise FileNotFoundError(f"No cache for {pdf_path.name}. Run without --skip-textract first.")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    blocks = _run_textract(pdf_path, bucket, region)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(blocks, default=str), encoding="utf-8")
    return blocks


def _clean(text: str) -> str:
    """Remove soft hyphens, collapse whitespace."""
    text = text.replace("\xad", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _get_child_text(block: dict, block_map: dict[str, dict]) -> str:
    """Get concatenated LINE text from a layout block's children."""
    lines = []
    for rel in block.get("Relationships", []):
        if rel["Type"] == "CHILD":
            for child_id in rel["Ids"]:
                child = block_map.get(child_id)
                if child and child["BlockType"] == "LINE":
                    lines.append(child["Text"])
    return " ".join(lines)


def _get_cell_text(cell: dict, block_map: dict[str, dict]) -> str:
    """Get text content of a table cell."""
    words = []
    for crel in cell.get("Relationships", []):
        if crel["Type"] == "CHILD":
            for wid in crel["Ids"]:
                w = block_map.get(wid)
                if w and w["BlockType"] == "WORD":
                    words.append(w["Text"])
    return " ".join(words)


def _extract_table(table_block: dict, block_map: dict[str, dict]) -> list[str]:
    """Extract table rows as pipe-separated text."""
    cells: list[tuple[int, int, str]] = []
    for rel in table_block.get("Relationships", []):
        if rel["Type"] == "CHILD":
            for cell_id in rel["Ids"]:
                cell = block_map.get(cell_id)
                if cell and cell["BlockType"] == "CELL":
                    cells.append((cell["RowIndex"], cell["ColumnIndex"], _get_cell_text(cell, block_map)))

    if not cells:
        return []

    max_row = max(c[0] for c in cells)
    rows = []
    for r in range(1, max_row + 1):
        row_cells = sorted([c for c in cells if c[0] == r], key=lambda x: x[1])
        row_text = " | ".join(c[2] for c in row_cells)
        if row_text.strip():
            rows.append(row_text)
    return rows


def _extract_list_items(block: dict, block_map: dict[str, dict]) -> list[str]:
    """Extract list items from a LAYOUT_LIST block."""
    items = []
    for rel in block.get("Relationships", []):
        if rel["Type"] == "CHILD":
            for child_id in rel["Ids"]:
                child = block_map.get(child_id)
                if child and child["BlockType"] == "LINE":
                    text = _clean(child["Text"])
                    if text:
                        items.append(f"- {text}")
    return items


def _handle_layout_title(
    layout_title: str,
    document_title: str,
    current_title: str,
    current_content: list[str],
    sections: list[dict[str, str]],
) -> tuple[str, str, list[str]]:
    """Use the first layout title as document title; later ones become section headers."""
    if not layout_title:
        return document_title, current_title, current_content
    if not document_title:
        return layout_title, current_title, current_content
    if layout_title == document_title:
        return document_title, current_title, current_content
    if current_title or current_content:
        sections.append({"title": current_title, "content": "\n".join(current_content)})
    return document_title, layout_title, []


def process_blocks(blocks: list[dict]) -> dict:
    """Convert Textract blocks into structured document dict."""
    block_map = {b["Id"]: b for b in blocks}

    title = ""
    sections: list[dict[str, str]] = []
    current_title = ""
    current_content: list[str] = []

    for block in blocks:
        bt = block["BlockType"]

        if bt == "LAYOUT_TITLE":
            layout_title = _clean(_get_child_text(block, block_map))
            title, current_title, current_content = _handle_layout_title(
                layout_title, title, current_title, current_content, sections
            )
        elif bt == "LAYOUT_SECTION_HEADER":
            if current_title or current_content:
                sections.append({"title": current_title, "content": "\n".join(current_content)})
            current_title = _clean(_get_child_text(block, block_map))
            current_content = []
        elif bt == "LAYOUT_TEXT":
            text = _clean(_get_child_text(block, block_map))
            if text:
                current_content.append(text)
        elif bt == "LAYOUT_LIST":
            current_content.extend(_extract_list_items(block, block_map))
        elif bt == "TABLE":
            current_content.extend(_extract_table(block, block_map))

    if current_title or current_content:
        sections.append({"title": current_title, "content": "\n".join(current_content)})

    return {"title": title, "sections": sections}


_SEMANTIC_TOKEN_RE = re.compile(r"\w+|[-%/§.,!?;:]", re.UNICODE)
_OCR_MATCH_THRESHOLD = 0.965


def _normalise_for_match(text: str) -> str:
    """Normalise text for conservative Textract/PDF similarity matching."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("„", '"').replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()


def _semantic_tokens(text: str) -> list[str]:
    """Return case-sensitive lexical and significant punctuation tokens."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("„", '"').replace("“", '"').replace("”", '"')
    return _SEMANTIC_TOKEN_RE.findall(re.sub(r"\s+", " ", text).strip())


def _pdf_paragraphs(pdf_path: Path) -> list[str]:
    """Extract collapsed paragraphs from a born-digital PDF text layer."""
    from pdfminer.high_level import extract_text

    text = extract_text(str(pdf_path))
    # Preserve lexical hyphens when pdfminer wraps a word at a line boundary.
    text = re.sub(r"(?<=\w)-[ \t]*\n(?=\w)", "-", text)
    paragraphs = []
    for paragraph in re.split(r"(?:\n\s*\n|\f)+", text):
        for line in paragraph.splitlines():
            cleaned_line = _clean(line)
            cleaned_line = re.sub(r"\s+([,.;:!?])", r"\1", cleaned_line)
            if cleaned_line:
                paragraphs.append(cleaned_line)
        cleaned = _clean(paragraph.replace("\n", " "))
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        # Collapse "7 7.1 ..." form-field number duplication onto one line.
        cleaned = re.sub(r"^(\d{1,2})\s+\1\.(\d+)\b", r"\1.\2", cleaned)
        if cleaned:
            paragraphs.append(cleaned)
    return list(dict.fromkeys(paragraphs))


def _count_token_sequence(tokens: list[str], sequence: list[str]) -> int:
    """Count occurrences of a short token sequence."""
    return sum(tokens[index : index + len(sequence)] == sequence for index in range(len(tokens) - len(sequence) + 1))


def _candidate_match(source_text: str, candidate: str, number_prefix: str | None) -> tuple[float, bool] | None:
    """Return similarity and exactness when a PDF candidate is safe to compare."""
    normalised = _normalise_for_match(source_text)
    source_tokens = _semantic_tokens(source_text)
    candidate_tokens = _semantic_tokens(candidate)
    if not source_tokens or not candidate_tokens:
        return None
    if candidate_tokens == source_tokens:
        return 1.0, True

    candidate_boundary_tokens = candidate_tokens
    candidate_for_similarity = candidate
    if candidate.startswith("- ") and not source_text.startswith("- "):
        candidate_boundary_tokens = candidate_tokens[1:]
        candidate_for_similarity = candidate[2:]
    if not candidate_boundary_tokens:
        return None

    # OCR repair must not expand or trim paragraph boundaries, only touch inner text.
    leading_edge_size = min(2, len(source_tokens), len(candidate_boundary_tokens))
    if (
        candidate_boundary_tokens[:leading_edge_size] != source_tokens[:leading_edge_size]
        or candidate_boundary_tokens[-1] != source_tokens[-1]
    ):
        return None

    if number_prefix:
        number_tokens = _semantic_tokens(number_prefix)
        if _count_token_sequence(candidate_tokens, number_tokens) > _count_token_sequence(source_tokens, number_tokens):
            return None

    candidate_similarity_normalised = _normalise_for_match(candidate_for_similarity)
    length_ratio = len(candidate_similarity_normalised) / len(normalised)
    if not 0.8 <= length_ratio <= 1.2:
        return None
    return SequenceMatcher(None, normalised, candidate_similarity_normalised, autojunk=False).ratio(), False


def _repair_text_from_candidates(text: str, candidates: list[str], *, allow_list_marker: bool = False) -> str:
    """Swap a likely OCR-corrupted string for a near-identical embedded PDF paragraph."""
    if len(_normalise_for_match(text)) < 12:
        return text

    best_text = text
    best_ratio = 0.0
    exact_semantic_match = False
    variants = [(text, "")]
    numbered_match = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", text)
    number_prefix = numbered_match.group(1) if numbered_match else None
    if numbered_match:
        variants.append((numbered_match.group(2), f"{number_prefix} "))

    for source_text, preserved_prefix in variants:
        for candidate in candidates:
            repair_candidate = candidate
            if not allow_list_marker and candidate.startswith("- ") and not source_text.startswith("- "):
                repair_candidate = candidate[2:]
            match = _candidate_match(source_text, repair_candidate, number_prefix)
            if match is None:
                continue
            ratio, is_exact = match
            if is_exact:
                exact_semantic_match = True
                continue
            if ratio > best_ratio:
                best_ratio = ratio
                best_text = f"{preserved_prefix}{repair_candidate}"

    # Repair only when the complete strings are near-identical — a changed
    # word/number/slash/percent is meaningful and must not be rewritten by typography drift.
    if not exact_semantic_match and best_ratio >= _OCR_MATCH_THRESHOLD:
        return best_text
    return text


def _separate_markdown_list_blocks(lines: list[str]) -> list[str]:
    """Insert blank lines where flattened PDF list blocks start or end."""
    separated: list[str] = []
    previous_is_bullet: bool | None = None
    for line in lines:
        if not line:
            if separated and separated[-1]:
                separated.append("")
            previous_is_bullet = None
            continue

        is_bullet = line.startswith("- ")
        if previous_is_bullet is not None and is_bullet != previous_is_bullet:
            separated.append("")
        separated.append(line)
        previous_is_bullet = is_bullet
    return separated


def repair_ocr_from_pdf(doc: dict, pdf_path: Path) -> int:
    """Rewrite near-identical Textract OCR output to the PDF's embedded text layer."""
    candidates = _pdf_paragraphs(pdf_path)
    if not candidates:
        logger.warning("No embedded text available for OCR reconciliation: %s", pdf_path.name)
        return 0

    repairs = 0

    repaired_title = _repair_text_from_candidates(doc.get("title", ""), candidates)
    if repaired_title != doc.get("title", ""):
        doc["title"] = repaired_title
        repairs += 1

    for section in doc.get("sections", []):
        repaired_section_title = _repair_text_from_candidates(section.get("title", ""), candidates)
        if repaired_section_title != section.get("title", ""):
            section["title"] = repaired_section_title
            repairs += 1

        repaired_lines = []
        for line in section.get("content", "").splitlines():
            repaired_line = _repair_text_from_candidates(line, candidates, allow_list_marker=True)
            repaired_lines.append(repaired_line)
            repairs += repaired_line != line
        section["content"] = "\n".join(_separate_markdown_list_blocks(repaired_lines))

    return repairs


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


def write_documents(docs: list[dict], output_dir: Path) -> None:
    """Write per-document Tier 2 JSON files."""
    docs_dir = output_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    for doc in docs:
        short_url = _derive_short_brochure_url(doc["doc_id"])
        if not short_url:
            logger.warning("Could not derive Kurzlink for doc_id '%s'", doc["doc_id"])

        out = {
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "category": "Merkblatt",
            "edition": "Online",
            "published": date.today().isoformat(),
            "brochure_number": doc["doc_id"],
            "brochure_url_short": short_url or "",
            "keywords": doc.get("keywords", []),
            "summary": doc.get("summary", ""),
            "sections": _split_large_sections(doc["sections"]),
        }
        path = docs_dir / f"{doc['doc_id']}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    logger.info("Wrote %d document files to %s", len(docs), docs_dir)


def write_kb_markdown(docs: list[dict], source_dir: Path) -> None:
    """Emit one structured ``{doc_id}.md`` per Merkblatt from the un-split sections (#501)."""
    source_dir.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        markdown = render_sections_to_markdown(doc)
        (source_dir / f"{doc['doc_id']}.md").write_text(markdown, encoding="utf-8")

    logger.info("Wrote %d Merkblatt Markdown files to %s", len(docs), source_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Merkblätter PDFs via Textract")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--skip-textract", action="store_true", help="Use cached Textract results")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    region = os.environ.get("AWS_REGION", "eu-central-1")
    pdf_files = sorted(args.input_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files in {args.input_dir}")

    logger.info("Processing %d PDFs", len(pdf_files))

    docs: list[dict] = []
    for pdf_path in pdf_files:
        blocks = _get_textract_blocks(pdf_path, args.cache_dir, args.bucket, region, skip=args.skip_textract)
        result = process_blocks(blocks)
        repairs = repair_ocr_from_pdf(result, pdf_path)
        result["doc_id"] = pdf_path.stem
        result["keywords"] = []
        result["category"] = "Merkblatt"
        docs.append(result)
        logger.info(
            "%s: %d sections, %d OCR repairs, title='%s'",
            result["doc_id"],
            len(result["sections"]),
            repairs,
            result["title"][:60],
        )

    import boto3

    model_id = os.environ.get("INDEX_GEN_MODEL_ID", "eu.amazon.nova-pro-v1:0")
    client = boto3.client("bedrock-runtime", region_name=region)
    generate_missing_keywords(client, model_id, docs)
    generate_summaries(client, model_id, docs)

    write_documents(docs, args.output_dir)
    # KB Markdown must come from the un-split sections (write_documents split a copy).
    write_kb_markdown(docs, args.source_dir)
    logger.info("Done.")


if __name__ == "__main__":
    main()
