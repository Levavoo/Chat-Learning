"""Detect structural defects in generated Knowledge-Base Markdown artifacts.

Pure, dependency-light scanner (stdlib + ``re``) so detectors are reusable by
the CI gate, unit tests, and any future in-Lambda pre-write guard. Mirrors the
report/acknowledgement engine of :mod:`etl.source_quality` (same ``decision``
and ``interim_handling`` vocabulary and the same ``(rule, source, prefix)`` matching).

Findings carry a ``tier`` (``hard`` or ``warning``). The gate fails when any
hard finding is unbaselined or any warning finding is unreviewed.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Rule id -> severity tier. ``hard`` fails unless baselined; ``warning`` fails if unreviewed.
RULE_TIERS: dict[str, str] = {
    "md.non-utf8": "hard",
    "md.empty-document": "hard",
    "md.control-character": "hard",
    "md.duplicate-leading-separator": "hard",
    "md.orphan-bullet": "hard",
    "md.empty-printed-page-reference": "hard",
    "md.embedded-pdf-page-counter": "warning",
    "md.split-boundary-start": "warning",
}

_VALID_DECISIONS = frozenset({"accepted", "source_fix_requested"})
_VALID_INTERIM_HANDLING = frozenset({"drop_fragment", "ingest_with_warning"})

_EXCERPT_LIMIT = 180

# C0 controls (except tab/newline/CR) plus DEL and C1 range; VT and FF included.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_THEMATIC_BREAK_RE = re.compile(r"[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*\Z")
_ORPHAN_BULLET_RE = re.compile(r"[ \t]*[-*+][ \t]*\Z")
# Empty printed-page reference: "Seite" + whitespace + clause terminator (page number dropped).
# The mandatory whitespace separates a dropped cross-reference from "zur Seite." (no space).
_EMPTY_PAGE_REF_RE = re.compile(r"\bSeite\s+[.)]")
# PDF page-counter noise: ``Seite X von Y`` and standalone ``- X -`` / ``X / Y`` lines.
_PAGE_COUNTER_INLINE_RE = re.compile(r"\bSeite\s+\d+\s+von\s+\d+\b", re.IGNORECASE)
_PAGE_COUNTER_LINE_RE = re.compile(r"[ \t]*(?:-\s*\d+\s*-|\d+\s*/\s*\d+)[ \t]*\Z")
_LOWERCASE_START_RE = re.compile(r"[a-zäöüß]")
_HEADING_RE = re.compile(r"#{1,6}\s")


@dataclass(frozen=True)
class MarkdownFinding:
    """A structural defect detected in one generated Markdown artifact."""

    rule: str
    tier: str
    source: str
    line: int
    column: int
    excerpt: str


def _escape_text(value: str, limit: int = _EXCERPT_LIMIT) -> str:
    r"""Render text as a single bounded line, escaping control chars as ``\xNN``."""
    out: list[str] = []
    for char in value:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            out.append(f"\\x{code:02x}")
        else:
            out.append(char)
    return "".join(out)[:limit]


def _escape_bytes(raw: bytes, limit: int = _EXCERPT_LIMIT) -> str:
    r"""Render raw bytes as a bounded ASCII line, escaping non-printables as ``\xNN``."""
    out: list[str] = []
    for byte in raw:
        if 0x20 <= byte < 0x7F:
            out.append(chr(byte))
        else:
            out.append(f"\\x{byte:02x}")
    return "".join(out)[:limit]


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Return the 1-based (line, column) for a character offset (newlines only)."""
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    column = offset - prefix.rfind("\n")
    return line, column


def _line_at(text: str, offset: int) -> str:
    """Return the newline-delimited line containing ``offset`` (unescaped)."""
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end]


def _first_finding(rule: str, source: str, line: int, column: int, excerpt: str) -> MarkdownFinding:
    return MarkdownFinding(rule=rule, tier=RULE_TIERS[rule], source=source, line=line, column=column, excerpt=excerpt)


def _detect_control_character(text: str, source: str) -> list[MarkdownFinding]:
    findings: list[MarkdownFinding] = []
    for match in _CONTROL_CHAR_RE.finditer(text):
        line, column = _line_col(text, match.start())
        findings.append(
            _first_finding("md.control-character", source, line, column, _escape_text(_line_at(text, match.start())))
        )
    return findings


def _detect_duplicate_leading_separator(text: str, source: str) -> list[MarkdownFinding]:
    body = text.lstrip("\ufeff")
    lines = body.split("\n")
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None or not _THEMATIC_BREAK_RE.fullmatch(lines[first]):
        return []
    second = next((i for i in range(first + 1, len(lines)) if lines[i].strip()), None)
    if second is None or not _THEMATIC_BREAK_RE.fullmatch(lines[second]):
        return []
    excerpt = _escape_text("\n".join(lines[first : second + 1]))
    return [_first_finding("md.duplicate-leading-separator", source, second + 1, 1, excerpt)]


def _detect_orphan_bullet(text: str, source: str) -> list[MarkdownFinding]:
    findings: list[MarkdownFinding] = []
    for index, raw_line in enumerate(text.split("\n")):
        if _ORPHAN_BULLET_RE.fullmatch(raw_line):
            findings.append(_first_finding("md.orphan-bullet", source, index + 1, 1, _escape_text(raw_line)))
    return findings


def _detect_empty_printed_page_reference(text: str, source: str) -> list[MarkdownFinding]:
    findings: list[MarkdownFinding] = []
    for match in _EMPTY_PAGE_REF_RE.finditer(text):
        line, column = _line_col(text, match.start())
        findings.append(
            _first_finding(
                "md.empty-printed-page-reference", source, line, column, _escape_text(_line_at(text, match.start()))
            )
        )
    return findings


def _detect_embedded_pdf_page_counter(text: str, source: str) -> list[MarkdownFinding]:
    findings: list[MarkdownFinding] = []
    for match in _PAGE_COUNTER_INLINE_RE.finditer(text):
        line, column = _line_col(text, match.start())
        findings.append(
            _first_finding("md.embedded-pdf-page-counter", source, line, column, _escape_text(match.group(0)))
        )
    for index, raw_line in enumerate(text.split("\n")):
        if _PAGE_COUNTER_LINE_RE.fullmatch(raw_line) and raw_line.strip():
            findings.append(
                _first_finding("md.embedded-pdf-page-counter", source, index + 1, 1, _escape_text(raw_line))
            )
    return findings


def _body_start(lines: list[str]) -> int | None:
    """Return the index of the first body line, skipping front-matter and a heading."""
    index = 0
    total = len(lines)
    # Skip a leading YAML front-matter block (`---` ... `---`).
    if index < total and _THEMATIC_BREAK_RE.fullmatch(lines[index]):
        closing = next((i for i in range(index + 1, total) if _THEMATIC_BREAK_RE.fullmatch(lines[i])), None)
        if closing is not None:
            index = closing + 1
    # Skip blank lines and a single leading heading.
    while index < total and not lines[index].strip():
        index += 1
    if index < total and _HEADING_RE.match(lines[index].lstrip()):
        index += 1
        while index < total and not lines[index].strip():
            index += 1
    return index if index < total else None


def _detect_split_boundary_start(text: str, source: str) -> list[MarkdownFinding]:
    lines = text.lstrip("\ufeff").split("\n")
    index = _body_start(lines)
    if index is None:
        return []
    stripped = lines[index].lstrip()
    first_char = stripped[:1]
    if first_char and _LOWERCASE_START_RE.match(first_char):
        return [_first_finding("md.split-boundary-start", source, index + 1, 1, _escape_text(stripped))]
    return []


def scan_markdown_bytes(raw: bytes, source: str) -> list[MarkdownFinding]:
    """Scan one Markdown artifact, handling non-UTF-8/empty before text rules."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [_first_finding("md.non-utf8", source, 0, 0, _escape_bytes(raw))]

    if not text.strip():
        return [_first_finding("md.empty-document", source, 0, 0, "")]

    findings: list[MarkdownFinding] = []
    findings.extend(_detect_control_character(text, source))
    findings.extend(_detect_duplicate_leading_separator(text, source))
    findings.extend(_detect_orphan_bullet(text, source))
    findings.extend(_detect_empty_printed_page_reference(text, source))
    findings.extend(_detect_embedded_pdf_page_counter(text, source))
    findings.extend(_detect_split_boundary_start(text, source))
    return findings


def scan_corpus(corpus_dir: Path) -> list[MarkdownFinding]:
    """Scan every ``*.md`` artifact below a corpus directory in deterministic order."""
    findings: list[MarkdownFinding] = []
    for path in sorted(corpus_dir.rglob("*.md")):
        source = path.relative_to(corpus_dir).as_posix()
        findings.extend(scan_markdown_bytes(path.read_bytes(), source))
    return findings


def load_acknowledgements(path: Path) -> list[dict[str, Any]]:
    """Load and validate reviewed markdown-quality decisions."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("acknowledgements"), list):
        raise ValueError("Acknowledgement file must have version=1 and an acknowledgements list")

    acknowledgements = payload["acknowledgements"]
    required = {"id", "rule", "source", "excerpt_prefix", "decision", "interim_handling", "rationale"}
    for acknowledgement in acknowledgements:
        missing = required - acknowledgement.keys()
        if missing:
            raise ValueError(f"Acknowledgement {acknowledgement.get('id', '<unknown>')} is missing: {sorted(missing)}")
        if acknowledgement["decision"] not in _VALID_DECISIONS:
            raise ValueError(f"Invalid decision for {acknowledgement['id']}: {acknowledgement['decision']}")
        if acknowledgement["interim_handling"] not in _VALID_INTERIM_HANDLING:
            raise ValueError(
                f"Invalid interim_handling for {acknowledgement['id']}: {acknowledgement['interim_handling']}"
            )
    return acknowledgements


def _source_matches(finding_source: str, ack_source: str) -> bool:
    """Match a finding source to an acknowledgement source.

    A trailing ``/`` matches every chunk under that document folder; otherwise exact match.
    """
    if ack_source.endswith("/"):
        return finding_source.startswith(ack_source)
    return finding_source == ack_source


def _matching_acknowledgement(
    finding: MarkdownFinding, acknowledgements: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for acknowledgement in acknowledgements:
        if (
            acknowledgement["rule"] == finding.rule
            and _source_matches(finding.source, acknowledgement["source"])
            and finding.excerpt.startswith(acknowledgement["excerpt_prefix"])
        ):
            return acknowledgement
    return None


def build_report(findings: list[MarkdownFinding], acknowledgements: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair findings with decisions; fail on unbaselined-hard or unreviewed-warning."""
    report_findings: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    hard_unbaselined = 0
    warning_unreviewed = 0

    for finding in findings:
        acknowledgement = _matching_acknowledgement(finding, acknowledgements)
        if acknowledgement is None:
            if finding.tier == "hard":
                hard_unbaselined += 1
            else:
                warning_unreviewed += 1
        else:
            matched_ids.add(acknowledgement["id"])
        report_findings.append({**asdict(finding), "acknowledgement": acknowledgement})

    stale_ids = [ack["id"] for ack in acknowledgements if ack["id"] not in matched_ids]
    unreviewed = hard_unbaselined + warning_unreviewed
    return {
        "version": 1,
        "status": "failed" if unreviewed else "passed",
        "summary": {
            "detected": len(findings),
            "acknowledged": len(findings) - unreviewed,
            "unreviewed": unreviewed,
            "hard_unbaselined": hard_unbaselined,
            "warning_unreviewed": warning_unreviewed,
            "stale_acknowledgements": len(stale_ids),
        },
        "stale_acknowledgement_ids": stale_ids,
        "findings": report_findings,
    }


def _print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "KB markdown-quality scan: "
        f"{summary['detected']} detected, "
        f"{summary['acknowledged']} acknowledged, "
        f"{summary['hard_unbaselined']} unbaselined-hard, "
        f"{summary['warning_unreviewed']} unreviewed-warning"
    )
    for finding in report["findings"]:
        acknowledgement = finding["acknowledgement"]
        if acknowledgement:
            level = "REVIEWED"
            decision = f"{acknowledgement['decision']}/{acknowledgement['interim_handling']}"
        else:
            level = "ERROR"
            decision = "unreviewed"
        print(
            f"{level}: {finding['source']}:{finding['line']}:{finding['column']} "
            f"{finding['rule']} [{finding['tier']}] ({decision}): {finding['excerpt']}"
        )
    for acknowledgement_id in report["stale_acknowledgement_ids"]:
        print(f"WARNING: stale markdown-quality acknowledgement: {acknowledgement_id}")


def main(argv: list[str] | None = None) -> int:
    """Run the markdown-quality gate against an already-generated corpus directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--acknowledgements", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    findings = scan_corpus(args.corpus_dir)
    acknowledgements = load_acknowledgements(args.acknowledgements)
    report = build_report(findings, acknowledgements)
    _print_report(report)

    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
