import dataclasses
import json
from pathlib import Path

import pytest

from etl.markdown_quality import (
    RULE_TIERS,
    MarkdownFinding,
    build_report,
    load_acknowledgements,
    main,
    scan_markdown_bytes,
)
from etl.markdown_quality_gate import build_baseline, generate_and_scan

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_SOURCE_DIR = REPO_ROOT / "cdk" / "seed-data" / "source"
ACKNOWLEDGEMENTS = REPO_ROOT / "cdk" / "seed-data" / "markdown-quality-acknowledgements.json"


def _only(findings: list[MarkdownFinding], rule: str) -> MarkdownFinding:
    matches = [f for f in findings if f.rule == rule]
    assert matches, f"expected a {rule} finding, got {[f.rule for f in findings]}"
    return matches[0]


def test_control_character_form_feed_fails_hard():
    findings = scan_markdown_bytes(b"---\nx: 1\n---\n## A\ntext\x0cmore\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.control-character")
    assert finding.tier == "hard"
    assert finding.source == "docs/d/d_0000.md"
    assert finding.line == 5
    assert "text\\x0cmore" in finding.excerpt
    assert build_report(findings, [])["status"] == "failed"


def test_duplicate_leading_separator_fails_hard():
    findings = scan_markdown_bytes(b"---\n---\n## A\nText\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.duplicate-leading-separator")
    assert finding.tier == "hard"
    assert finding.line == 2
    assert build_report(findings, [])["status"] == "failed"


def test_orphan_bullet_fails_hard():
    findings = scan_markdown_bytes(b"## A\n\n- \n\nmore\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.orphan-bullet")
    assert finding.tier == "hard"
    assert finding.line == 3
    assert build_report(findings, [])["status"] == "failed"


def test_empty_printed_page_reference_fails_hard():
    """Real calibrated construct: dropped page cross-reference "auf Seite ." (not "[]()")."""
    findings = scan_markdown_bytes(b"## A\n\nMehr dazu auf Seite .\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.empty-printed-page-reference")
    assert finding.tier == "hard"
    assert finding.line == 3
    assert "Seite ." in finding.excerpt
    assert build_report(findings, [])["status"] == "failed"


def test_non_utf8_fails_hard_whole_file():
    findings = scan_markdown_bytes(b"\xff\xfe## A", "docs/d/d_0000.md")
    assert findings == [MarkdownFinding("md.non-utf8", "hard", "docs/d/d_0000.md", 0, 0, "\\xff\\xfe## A")]
    assert build_report(findings, [])["status"] == "failed"


def test_empty_document_fails_hard():
    findings = scan_markdown_bytes(b"   \n\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.empty-document")
    assert finding.tier == "hard"
    assert finding.line == 0


def test_ordinary_sentence_ending_seite_is_not_a_page_reference():
    """"zur Seite." (noun, no space before period) must not be flagged."""
    findings = scan_markdown_bytes(b"---\nname: X\n---\n## A\n\nEr stand ihr zur Seite.\n", "docs/d/d_0000.md")
    assert [f for f in findings if f.rule == "md.empty-printed-page-reference"] == []


def test_split_boundary_start_warning_unreviewed_fails():
    findings = scan_markdown_bytes(b"## A\n\nersicherungstraeger und mehr\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.split-boundary-start")
    assert finding.tier == "warning"
    report = build_report(findings, [])
    assert report["status"] == "failed"
    assert report["summary"]["warning_unreviewed"] == 1


def test_warning_passes_with_accepted_policy_entry():
    findings = scan_markdown_bytes(b"## A\n\nersicherungstraeger und mehr\n", "docs/d/d_0000.md")
    acknowledgements = [
        {
            "id": "policy-1",
            "rule": "md.split-boundary-start",
            "source": "docs/d/d_0000.md",
            "excerpt_prefix": "ersicherungstraeger",
            "decision": "accepted",
            "interim_handling": "ingest_with_warning",
            "rationale": "Legit lowercase continuation.",
        }
    ]
    report = build_report(findings, acknowledgements)
    assert report["status"] == "passed"
    assert report["summary"]["acknowledged"] == 1


def test_embedded_page_counter_is_warning():
    findings = scan_markdown_bytes(b"## A\n\nSeite 3 von 16\n", "docs/d/d_0000.md")
    finding = _only(findings, "md.embedded-pdf-page-counter")
    assert finding.tier == "warning"


def test_baseline_source_fix_requested_passes():
    findings = scan_markdown_bytes(b"## A\n\nText\x0cmehr\n", "docs/d/d_0000.md")
    acknowledgements = [
        {
            "id": "b1",
            "rule": "md.control-character",
            "source": "docs/d/d_0000.md",
            "excerpt_prefix": "",
            "decision": "source_fix_requested",
            "interim_handling": "drop_fragment",
            "rationale": "#694 pending #501 regen.",
        }
    ]
    report = build_report(findings, acknowledgements)
    assert report["status"] == "passed"
    assert report["summary"]["acknowledged"] == 1
    assert report["summary"]["stale_acknowledgements"] == 0


def test_document_prefix_source_matches_all_chunks():
    findings = scan_markdown_bytes(b"## A\n\nText\x0cmehr\n", "docs/G0103/G0103_0005.md")
    acknowledgements = [
        {
            "id": "doc1",
            "rule": "md.control-character",
            "source": "docs/G0103/",
            "excerpt_prefix": "",
            "decision": "source_fix_requested",
            "interim_handling": "drop_fragment",
            "rationale": "#694 baseline for the whole document.",
        }
    ]
    report = build_report(findings, acknowledgements)
    assert report["status"] == "passed"


def test_document_prefix_does_not_leak_to_sibling_documents():
    findings = scan_markdown_bytes(b"## A\n\nText\x0cmehr\n", "docs/G01039/G01039_0000.md")
    acknowledgements = [
        {
            "id": "doc1",
            "rule": "md.control-character",
            "source": "docs/G0103/",
            "excerpt_prefix": "",
            "decision": "source_fix_requested",
            "interim_handling": "drop_fragment",
            "rationale": "prefix must not leak",
        }
    ]
    report = build_report(findings, acknowledgements)
    assert report["status"] == "failed"
    assert report["summary"]["stale_acknowledgements"] == 1


def test_stale_acknowledgement_is_surfaced():
    acknowledgements = [
        {
            "id": "stale-1",
            "rule": "md.control-character",
            "source": "docs/gone/",
            "excerpt_prefix": "",
            "decision": "source_fix_requested",
            "interim_handling": "drop_fragment",
            "rationale": "corpus already clean",
        }
    ]
    report = build_report([], acknowledgements)
    assert report["status"] == "passed"
    assert report["stale_acknowledgement_ids"] == ["stale-1"]
    assert report["summary"]["stale_acknowledgements"] == 1


def test_load_acknowledgements_rejects_invalid_decision(tmp_path):
    path = tmp_path / "ack.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "acknowledgements": [
                {
                    "id": "x",
                    "rule": "md.control-character",
                    "source": "docs/d/",
                    "excerpt_prefix": "",
                    "decision": "invalid",
                    "interim_handling": "drop_fragment",
                    "rationale": "r",
                }
            ],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Invalid decision"):
        load_acknowledgements(path)


def test_load_acknowledgements_rejects_missing_field(tmp_path):
    path = tmp_path / "ack.json"
    path.write_text(
        json.dumps({"version": 1, "acknowledgements": [{"id": "x", "rule": "md.control-character"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing"):
        load_acknowledgements(path)


def test_every_emitted_rule_has_a_tier():
    for rule in RULE_TIERS.values():
        assert rule in {"hard", "warning"}


def test_scanner_cli_exits_nonzero_on_bad_artifact(tmp_path):
    corpus = tmp_path / "docs" / "d"
    corpus.mkdir(parents=True)
    (corpus / "d_0000.md").write_bytes(b"## A\ntext\x0cmore\n")
    ack = tmp_path / "ack.json"
    ack.write_text('{"version": 1, "acknowledgements": []}', encoding="utf-8")
    report_path = tmp_path / "report.json"

    exit_code = main(["--corpus-dir", str(tmp_path), "--acknowledgements", str(ack), "--report", str(report_path)])

    assert exit_code == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "failed"


@pytest.fixture(scope="module")
def generated_corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("mdq-corpus")
    findings = generate_and_scan(SEED_SOURCE_DIR, out)
    return out, findings


def test_seed_corpus_findings_are_all_reviewed(generated_corpus):
    _, findings = generated_corpus
    report = build_report(findings, load_acknowledgements(ACKNOWLEDGEMENTS))

    assert report["status"] == "passed"
    assert report["summary"]["hard_unbaselined"] == 0
    assert report["summary"]["warning_unreviewed"] == 0
    assert report["summary"]["stale_acknowledgements"] == 0


def test_generated_corpus_covers_primary_and_subdocuments(generated_corpus):
    corpus, _ = generated_corpus
    names = {p.name for p in corpus.rglob("*.md")}
    assert any(n.endswith("_0000.md") and "_table_" not in n and "_note_" not in n for n in names)
    assert any("_table_" in n for n in names)
    assert any("_note_" in n for n in names)


def test_scanner_cli_passes_on_baselined_corpus(generated_corpus):
    corpus, _ = generated_corpus
    exit_code = main(["--corpus-dir", str(corpus), "--acknowledgements", str(ACKNOWLEDGEMENTS)])
    assert exit_code == 0


def test_offline_generation_is_deterministic(generated_corpus, tmp_path_factory):
    _, first = generated_corpus
    second = generate_and_scan(SEED_SOURCE_DIR, tmp_path_factory.mktemp("mdq-corpus-2"))
    assert [dataclasses.astuple(f) for f in second] == [dataclasses.astuple(f) for f in first]


def test_generated_baseline_matches_committed_baseline(generated_corpus):
    """Fresh baseline from the live corpus must reproduce the committed entry ids."""
    _, findings = generated_corpus
    emitted_ids = {a["id"] for a in build_baseline(findings)["acknowledgements"]}
    committed_ids = {a["id"] for a in load_acknowledgements(ACKNOWLEDGEMENTS)}
    assert emitted_ids == committed_ids


def test_acknowledgement_file_is_reviewable_json():
    payload = json.loads(ACKNOWLEDGEMENTS.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert isinstance(payload["acknowledgements"], list)
