import json
from pathlib import Path

from etl.source_quality import (
    EMPTY_SINGLE_COLUMN_CELL_RULE,
    LOWERCASE_CONTINUATION_HEAD_RULE,
    SourceQualityFinding,
    build_report,
    load_acknowledgements,
    main,
    scan_corpus,
    scan_xml,
    starts_with_lowercase_continuation,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED_SOURCE_DIR = REPO_ROOT / "cdk" / "seed-data" / "source"
ACKNOWLEDGEMENTS = REPO_ROOT / "cdk" / "seed-data" / "source-quality-acknowledgements.json"


def test_detects_text_after_empty_cell_in_single_column_table(tmp_path):
    xml = tmp_path / "sample.xml"
    xml.write_text(
        """<topic><title>Document</title><body>
        <section><title>Section</title>
          <p otherprops="note-ueberschrift">Flow</p>
          <table><tgroup cols="1"><tbody>
            <row><entry/></row>
            <row><entry><p>Fragment starts here.</p></entry></row>
          </tbody></tgroup></table>
        </section>
        </body></topic>""",
        encoding="utf-8",
    )

    assert scan_xml(xml) == [
        SourceQualityFinding(
            rule=EMPTY_SINGLE_COLUMN_CELL_RULE,
            source="sample.xml",
            document_title="Document",
            section_title="Section",
            table_title="Flow",
            table_index=0,
            row_index=1,
            passage="Fragment starts here.",
        )
    ]


def test_ignores_empty_rows_in_multi_column_data_tables(tmp_path):
    xml = tmp_path / "sample.xml"
    xml.write_text(
        """<topic><body><table><tgroup cols="2"><tbody>
          <row><entry/><entry/></row>
          <row><entry>A</entry><entry>B</entry></row>
        </tbody></tgroup></table></body></topic>""",
        encoding="utf-8",
    )

    assert scan_xml(xml) == []


def test_unreviewed_finding_fails_report(tmp_path):
    xml = tmp_path / "sample.xml"
    xml.write_text(
        """<topic><body><table><tgroup cols="1"><tbody>
          <row><entry/></row><row><entry>Broken fragment.</entry></row>
        </tbody></tgroup></table></body></topic>""",
        encoding="utf-8",
    )

    report = build_report(scan_xml(xml), [])

    assert report["status"] == "failed"
    assert report["summary"]["unreviewed"] == 1


def test_cli_exits_nonzero_for_unreviewed_finding(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "sample.xml").write_text(
        """<topic><body><table><tgroup cols="1"><tbody>
          <row><entry/></row><row><entry>Broken fragment.</entry></row>
        </tbody></tgroup></table></body></topic>""",
        encoding="utf-8",
    )
    acknowledgements = tmp_path / "acknowledgements.json"
    acknowledgements.write_text(
        '{"version": 1, "acknowledgements": []}',
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    exit_code = main([
        "--source-dir",
        str(source_dir),
        "--acknowledgements",
        str(acknowledgements),
        "--report",
        str(report_path),
    ])

    assert exit_code == 1
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "failed"


def test_seed_corpus_findings_are_all_reviewed():
    findings = scan_corpus(SEED_SOURCE_DIR)
    acknowledgements = load_acknowledgements(ACKNOWLEDGEMENTS)
    report = build_report(findings, acknowledgements)

    assert report["status"] == "passed"
    assert report["summary"] == {
        "detected": 0,
        "acknowledged": 0,
        "unreviewed": 0,
        "stale_acknowledgements": 0,
    }
    assert report["findings"] == []


def test_acknowledgement_file_is_reviewable_json():
    payload = json.loads(ACKNOWLEDGEMENTS.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert payload["acknowledgements"] == []


def test_lowercase_continuation_head_predicate():
    """Class-a signal (#695): lower-case head marks a truncated continuation."""
    assert starts_with_lowercase_continuation("sunfähig sind und die Krankenkasse ...")
    assert starts_with_lowercase_continuation("  ersicherungsträger, Arbeitsagenturen")
    assert not starts_with_lowercase_continuation("Hausarzt beifügen.")
    assert not starts_with_lowercase_continuation("## Überschrift")
    assert not starts_with_lowercase_continuation("3.1 Leistungen")
    assert not starts_with_lowercase_continuation("")


def test_new_rule_constant_is_distinct():
    """Class-a rule name is distinct from the #680 empty-cell rule."""
    assert LOWERCASE_CONTINUATION_HEAD_RULE != EMPTY_SINGLE_COLUMN_CELL_RULE
