"""Detect structurally suspicious passages in the DITA seed corpus."""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

EMPTY_SINGLE_COLUMN_CELL_RULE = "single-column-empty-cell-before-text"
# A head that opens lower-case is a deterministic marker of truncation at source,
# since German section heads and sentences capitalise. Reusable predicate; does
# NOT change scan_corpus — confirmed findings go through explicit acknowledgements.
LOWERCASE_CONTINUATION_HEAD_RULE = "lowercase-continuation-head"
_VALID_DECISIONS = frozenset({"accepted", "source_fix_requested"})
_VALID_INTERIM_HANDLING = frozenset({"drop_fragment", "ingest_with_warning"})


def starts_with_lowercase_continuation(passage: str) -> bool:
    """Return whether ``passage`` opens with a lower-case mid-clause continuation."""
    stripped = passage.lstrip()
    if not stripped:
        return False
    first = stripped[0]
    return first.isalpha() and first.islower()


@dataclass(frozen=True)
class SourceQualityFinding:
    """A suspicious source passage requiring an explicit editorial decision."""

    rule: str
    source: str
    document_title: str
    section_title: str
    table_title: str
    table_index: int
    row_index: int
    passage: str


def _element_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).replace("\ufeff", "").split())


def _nearest_section_title(table: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    ancestor = parents.get(table)
    while ancestor is not None:
        if ancestor.tag.lower() == "section":
            return _element_text(ancestor.find("title"))
        ancestor = parents.get(ancestor)
    return ""


def _table_title(table: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    explicit_title = _element_text(table.find("title"))
    if explicit_title:
        return explicit_title

    parent = parents.get(table)
    if parent is None:
        return ""
    siblings = list(parent)
    table_position = siblings.index(table)
    if table_position == 0:
        return ""
    previous = siblings[table_position - 1]
    if previous.tag.lower() == "p" and previous.get("otherprops") == "note-ueberschrift":
        return _element_text(previous).rstrip(":").strip()
    return ""


def scan_xml(path: Path, source_name: str | None = None) -> list[SourceQualityFinding]:
    """Return high-confidence truncation findings from one DITA XML file."""
    root = ET.parse(path).getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    document_title = _element_text(root.find("title"))
    findings: list[SourceQualityFinding] = []

    for table_index, table in enumerate(root.iter("table")):
        section_title = _nearest_section_title(table, parents)
        table_title = _table_title(table, parents)
        for tgroup in table.iter("tgroup"):
            if (tgroup.get("cols") or "").strip() != "1":
                continue

            previous_row_empty = False
            for row_index, row in enumerate(tgroup.iter("row")):
                entries = list(row.findall("entry"))
                entry_texts = [_element_text(entry) for entry in entries]
                row_empty = bool(entries) and not any(entry_texts)

                if previous_row_empty:
                    passage = next((text for text in entry_texts if text), "")
                    if passage:
                        findings.append(
                            SourceQualityFinding(
                                rule=EMPTY_SINGLE_COLUMN_CELL_RULE,
                                source=source_name or path.name,
                                document_title=document_title,
                                section_title=section_title,
                                table_title=table_title,
                                table_index=table_index,
                                row_index=row_index,
                                passage=passage,
                            )
                        )
                previous_row_empty = row_empty

    return findings


def scan_corpus(source_dir: Path) -> list[SourceQualityFinding]:
    """Scan all XML files below a seed-corpus directory."""
    findings: list[SourceQualityFinding] = []
    for path in sorted(source_dir.rglob("*.xml")):
        findings.extend(scan_xml(path, source_name=path.relative_to(source_dir).as_posix()))
    return findings


def load_acknowledgements(path: Path) -> list[dict[str, Any]]:
    """Load and validate reviewed source-quality decisions."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("acknowledgements"), list):
        raise ValueError("Acknowledgement file must have version=1 and an acknowledgements list")

    acknowledgements = payload["acknowledgements"]
    required = {"id", "rule", "source", "passage_prefix", "decision", "interim_handling", "rationale"}
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


def _matching_acknowledgement(
    finding: SourceQualityFinding, acknowledgements: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for acknowledgement in acknowledgements:
        if (
            acknowledgement["rule"] == finding.rule
            and acknowledgement["source"] == finding.source
            and finding.passage.startswith(acknowledgement["passage_prefix"])
        ):
            return acknowledgement
    return None


def build_report(findings: list[SourceQualityFinding], acknowledgements: list[dict[str, Any]]) -> dict[str, Any]:
    """Pair findings with decisions and summarize unreviewed/stale entries."""
    report_findings: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    unreviewed = 0

    for finding in findings:
        acknowledgement = _matching_acknowledgement(finding, acknowledgements)
        if acknowledgement is None:
            unreviewed += 1
        else:
            matched_ids.add(acknowledgement["id"])
        report_findings.append({
            **asdict(finding),
            "acknowledgement": acknowledgement,
        })

    stale_ids = [
        acknowledgement["id"] for acknowledgement in acknowledgements if acknowledgement["id"] not in matched_ids
    ]
    return {
        "version": 1,
        "status": "failed" if unreviewed else "passed",
        "summary": {
            "detected": len(findings),
            "acknowledged": len(findings) - unreviewed,
            "unreviewed": unreviewed,
            "stale_acknowledgements": len(stale_ids),
        },
        "stale_acknowledgement_ids": stale_ids,
        "findings": report_findings,
    }


def _print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "Seed source-quality scan: "
        f"{summary['detected']} detected, "
        f"{summary['acknowledged']} acknowledged, "
        f"{summary['unreviewed']} unreviewed"
    )
    for finding in report["findings"]:
        acknowledgement = finding["acknowledgement"]
        level = "WARNING" if acknowledgement else "ERROR"
        decision = (
            f"{acknowledgement['decision']}/{acknowledgement['interim_handling']}" if acknowledgement else "unreviewed"
        )
        print(
            f"{level}: {finding['source']} table[{finding['table_index']}] "
            f"row[{finding['row_index']}] {finding['rule']} ({decision}): "
            f"{finding['passage'][:180]}"
        )
    for acknowledgement_id in report["stale_acknowledgement_ids"]:
        print(f"WARNING: stale source-quality acknowledgement: {acknowledgement_id}")


def main(argv: list[str] | None = None) -> int:
    """Run the seed-corpus quality gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--acknowledgements", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    findings = scan_corpus(args.source_dir)
    acknowledgements = load_acknowledgements(args.acknowledgements)
    report = build_report(findings, acknowledgements)
    _print_report(report)

    if args.report:
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 1 if report["summary"]["unreviewed"] else 0


if __name__ == "__main__":
    sys.exit(main())
