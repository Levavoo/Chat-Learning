"""Read-only audit: classify malformed chunk-*start* fragments (#695).

Regenerates each source doc with the real transforms (mirroring the live
CHUNK_MARKDOWN routing) and classifies every lower-case / non-list chunk
start via ``etl.chunk_start_quality``. Two modes: ``--from-source`` runs
fully offline; ``--docs-dir`` compares a locally-materialised copy of the
live KB docs/ tree against the current-code regeneration.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import etl.transform  # noqa: F401  (side effect: registers every transform)
from etl import source_quality
from etl.chunk_start_quality import (
    build_classification_report,
    classify_start,
    first_content_line,
    is_lowercase_nonlist_start,
    load_chunk_start_acknowledgements,
)
from etl.transform.base import Transform
from etl.util.chunking import (
    FlatSectionChunkingStrategy,
    GlossaryChunkingStrategy,
    HierarchicalChunkingStrategy,
)
from etl.util.chunking.base import Chunk
from etl.util.chunking.text_splitter import starts_mid_token

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SOURCE_DIR = _REPO_ROOT / "cdk" / "seed-data" / "source"
_SOURCE_ACKS = _REPO_ROOT / "cdk" / "seed-data" / "source-quality-acknowledgements.json"
_START_ACKS = _REPO_ROOT / "cdk" / "seed-data" / "chunk-start-acknowledgements.json"

# DITA chain up to (not including) CHUNK_MARKDOWN; CHUNK_MARKDOWN is run via the
# strategy directly to skip the transform's LLM-enrichment side effects.
_DITA_TO_MARKDOWN = ("META_FROM_DITA", "EXTRACT_DITA_NOTES", "EXTRACT_DITA_TABLES", "DITA2HTML", "TEXT2MD")

_HEAD_PROBE_LEN = 48


def _chunk_start_mid_token(markdown: str, content: str) -> bool:
    r"""Whether ``content``'s start lands mid-token in the pre-chunk Markdown ``M``.

    Locates the chunk by a long content prefix (not the first line): a short
    first line like ``"der"`` also occurs inside ``"oder"`` or ``"wieder"`` and
    would falsely match in-word. Non-contiguous chunks (oversized paragraphs
    re-split and rejoined on ``\n\n``) start on clean boundaries, so a -1
    ``find`` conservatively reports not-mid-token.
    """
    offset = markdown.find(content[:_HEAD_PROBE_LEN])
    return starts_mid_token(markdown, offset) if offset > 0 else False


@dataclass
class RegenChunk:
    name: str
    chunk_type: str
    section_title: str
    first_line: str
    mid_token: bool


def _select_strategy(markdown: str, brochure_number: str, is_pdf: bool):
    """Mirror chunk_markdown._select_chunking_strategy (routing only)."""
    if brochure_number in ("B28", "B37"):
        return GlossaryChunkingStrategy()
    if brochure_number == "B38":
        return FlatSectionChunkingStrategy(enable_headerless_fallback=is_pdf)
    if markdown.count("\n### ") >= 3:
        return HierarchicalChunkingStrategy()
    return FlatSectionChunkingStrategy(enable_headerless_fallback=is_pdf)


def _markdown_from_pdf(pdf_bytes: bytes) -> str:
    from markitdown_no_magika import MarkItDown

    return MarkItDown().convert_stream(BytesIO(pdf_bytes), file_extension=".pdf").markdown


def _markdown_from_dita(xml_text: str, base: str) -> str:
    """Run the DITA chain up to TEXT2MD and return the pre-chunk Markdown."""
    from etl.models import DataObject, DataType, PipelineItem, SourceObject

    source = SourceObject(name=base, data_type=DataType.XML, source="local", metadata={})
    item = PipelineItem(
        name=base,
        source_object=source,
        data_object=DataObject(name=base, data=xml_text, data_type=DataType.XML, metadata={}),
    )
    items = [item]
    for transform_type in _DITA_TO_MARKDOWN:
        transform = Transform.create(transform_type)
        items = [out for current in items for out in transform.apply(current)]
    data = items[0].data_object.data if items else ""
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


def regenerate(source_path: Path) -> tuple[str, list[RegenChunk]]:
    """Return (pre-chunk Markdown M, current chunk set) for one source doc."""
    base = source_path.stem
    is_pdf = source_path.suffix.lower() == ".pdf"
    if is_pdf:
        markdown = _markdown_from_pdf(source_path.read_bytes())
    else:
        markdown = _markdown_from_dita(source_path.read_text(encoding="utf-8"), base)

    strategy = _select_strategy(markdown, base, is_pdf)
    metadata: dict[str, Any] = {"brochure_number": base, "name": base}

    regen: list[RegenChunk] = []
    index = 0
    for chunk in strategy.chunk(markdown, metadata):
        content = chunk.content.strip() if isinstance(chunk, Chunk) else str(chunk).strip()
        if not content:
            continue
        name = f"{base}/{base}_{index:04d}"
        index += 1
        head = first_content_line(content)
        mid_token = _chunk_start_mid_token(markdown, content)
        chunk_type = chunk.metadata.get("chunk_type", "") if isinstance(chunk, Chunk) else ""
        section_title = chunk.metadata.get("section_title", "") if isinstance(chunk, Chunk) else ""
        regen.append(RegenChunk(name, chunk_type, section_title, head, mid_token))
    return markdown, regen


def _source_truncation(source_path: Path) -> bool:
    """Whether a source-quality scan flags truncation (XML only)."""
    if source_path.suffix.lower() != ".xml":
        return False
    return bool(source_quality.scan_xml(source_path))


def _finding(source_key: str, pipeline: str, regen: RegenChunk, cause: str, disposition: str) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "first_content_line": regen.first_line,
        "pipeline": pipeline,
        "chunk_type": regen.chunk_type,
        "section_title": regen.section_title,
        "regenerated_mid_token": regen.mid_token,
        "cause": cause,
        "disposition": disposition,
    }


def audit_from_source(source_dir: Path) -> list[dict[str, Any]]:
    """Offline post-fix verification: ``splitter_defect`` must be 0 after the #695 fix."""
    findings: list[dict[str, Any]] = []
    sources = sorted([*source_dir.rglob("*.xml"), *source_dir.rglob("*.pdf")])
    for source_path in sources:
        pipeline = "PDF_PROCESSING" if source_path.suffix.lower() == ".pdf" else "DITA_XML_PROCESSING"
        try:
            _markdown, regen = regenerate(source_path)
        except Exception as error:  # one bad source must not abort the whole audit
            findings.append({
                "source_key": source_path.name,
                "first_content_line": "",
                "pipeline": pipeline,
                "chunk_type": "",
                "section_title": "",
                "regenerated_mid_token": False,
                "cause": "unclassified_regeneration_error",
                "disposition": f"manual_review:{type(error).__name__}",
            })
            continue
        truncated = _source_truncation(source_path)
        for chunk in regen:
            if not is_lowercase_nonlist_start(chunk.first_line):
                continue
            cause, disposition = classify_start(
                regenerated_start_malformed=True,
                regenerated_start_mid_token=chunk.mid_token,
                chunk_type=chunk.chunk_type,
                source_truncation=truncated,
            )
            findings.append(_finding(source_path.name, pipeline, chunk, cause, disposition))
    return findings


def _read_live_docs_local(docs_dir: Path) -> list[tuple[str, str, dict[str, Any]]]:
    """Read local KB docs/ (.md + .metadata.json). Returns (key, first_line, sidecar)."""
    docs: list[tuple[str, str, dict[str, Any]]] = []
    for md_path in sorted(docs_dir.rglob("*.md")):
        first_line = first_content_line(md_path.read_text(encoding="utf-8"))
        sidecar_path = md_path.with_suffix(md_path.suffix + ".metadata.json")
        sidecar: dict[str, Any] = {}
        if sidecar_path.exists():
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        docs.append((md_path.relative_to(docs_dir).as_posix(), first_line, sidecar))
    return docs


def audit_live(docs_dir: Path, source_dir: Path) -> list[dict[str, Any]]:
    """Classify materialised KB docs against the current-code regeneration (uses evidence, not positions)."""
    findings: list[dict[str, Any]] = []
    regen_cache: dict[str, tuple[str, list[RegenChunk]]] = {}
    for key, first_line, sidecar in _read_live_docs_local(docs_dir):
        if not is_lowercase_nonlist_start(first_line):
            continue
        base = key.split("/", 1)[0]
        source_path = _resolve_source(source_dir, base)
        if source_path is None:
            findings.append({
                "source_key": key,
                "first_content_line": first_line,
                "pipeline": sidecar.get("pipeline", "unknown"),
                "chunk_type": sidecar.get("chunk_type", ""),
                "section_title": sidecar.get("section_title", ""),
                "regenerated_mid_token": False,
                "cause": "unclassified_missing_source",
                "disposition": "manual_review:source_not_found",
            })
            continue
        if base not in regen_cache:
            regen_cache[base] = regenerate(source_path)
        _markdown, regen = regen_cache[base]
        by_name = {chunk.name: chunk for chunk in regen}
        chunk_type = sidecar.get("chunk_type", "")
        regen_chunk = by_name.get(key.rsplit(".md", 1)[0])
        residual_mid_token = any(c.mid_token for c in regen if c.chunk_type.endswith("_split"))
        if regen_chunk is not None:
            malformed = regen_chunk.mid_token or is_lowercase_nonlist_start(regen_chunk.first_line)
            mid_token = regen_chunk.mid_token
        else:
            malformed = residual_mid_token or _source_truncation(source_path)
            mid_token = residual_mid_token
        cause, disposition = classify_start(
            regenerated_start_malformed=malformed,
            regenerated_start_mid_token=mid_token,
            chunk_type=chunk_type,
            source_truncation=_source_truncation(source_path),
        )
        findings.append({
            "source_key": key,
            "first_content_line": first_line,
            "pipeline": sidecar.get("pipeline", "unknown"),
            "chunk_type": chunk_type,
            "section_title": sidecar.get("section_title", ""),
            "regenerated_mid_token": mid_token,
            "cause": cause,
            "disposition": disposition,
        })
    return findings


def _resolve_source(source_dir: Path, base: str) -> Path | None:
    for suffix in (".xml", ".pdf"):
        candidate = next(iter(source_dir.rglob(f"{base}{suffix}")), None)
        if candidate is not None:
            return candidate
    return None


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Chunk-start classification (#695)",
        "",
        f"- total findings: {summary['total']}",
        f"- unresolved: {summary['unresolved']}",
        f"- by cause: {json.dumps(summary['by_cause'], ensure_ascii=False)}",
        "",
        "| source_key | first line | pipeline | chunk_type | cause | disposition | resolved |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for finding in report["findings"]:
        first = finding["first_content_line"][:60].replace("|", "\\|")
        lines.append(
            f"| {finding['source_key']} | {first} | {finding['pipeline']} | "
            f"{finding['chunk_type']} | {finding['cause']} | {finding['disposition']} | "
            f"{'yes' if finding['resolved'] else 'NO'} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-source",
        action="store_true",
        help="Offline: regenerate from local source and classify current-code starts (no AWS).",
    )
    parser.add_argument("--docs-dir", type=Path, help="Local KB docs/ dir (*.md + *.metadata.json).")
    parser.add_argument("--source-dir", type=Path, default=_DEFAULT_SOURCE_DIR)
    parser.add_argument("--report", type=Path, help="Write the JSON classification report here.")
    parser.add_argument("--markdown-report", type=Path, help="Write the Markdown table here.")
    args = parser.parse_args(argv)

    if args.from_source:
        findings = audit_from_source(args.source_dir)
    elif args.docs_dir is not None:
        findings = audit_live(args.docs_dir, args.source_dir)
    else:
        parser.error("provide --from-source or --docs-dir (live S3 discovery is a documented ops extension)")
        return 2

    report = build_classification_report(
        findings,
        source_acknowledgements=source_quality.load_acknowledgements(_SOURCE_ACKS) if _SOURCE_ACKS.exists() else [],
        start_acknowledgements=load_chunk_start_acknowledgements(_START_ACKS) if _START_ACKS.exists() else [],
    )

    print(
        f"Chunk-start audit: {report['summary']['total']} findings, "
        f"{report['summary']['unresolved']} unresolved, by cause {report['summary']['by_cause']}"
    )
    splitter_defects = report["summary"]["by_cause"].get("splitter_defect", 0)
    print(f"splitter_defect (must be 0 after the #695 fix): {splitter_defects}")
    if args.from_source:
        # Offline pass signal is splitter_defect == 0, NOT overall exit 0;
        # permitted_continuation remainders are #501, not #695.
        print(
            "Offline pass criterion: splitter_defect == 0. Remaining unresolved "
            "'permitted_continuation' starts are clean-boundary PDF continuations "
            "(#501, out of #695 scope), not a #695 regression."
        )

    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_report:
        args.markdown_report.write_text(_render_markdown(report), encoding="utf-8")

    return 1 if report["summary"]["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
