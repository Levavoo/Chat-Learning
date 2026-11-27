"""Tests for the deterministic chunk-start classifier (#695)."""

import json
from pathlib import Path

import pytest

from etl.chunk_start_quality import (
    CAUSE_PERMITTED_CONTINUATION,
    CAUSE_SOURCE_TRUNCATION,
    CAUSE_SPLITTER_DEFECT,
    CAUSE_STALE_ARTIFACT,
    DISPOSITION_FIX_SPLITTER,
    DISPOSITION_PERMITTED,
    DISPOSITION_REPROCESS_ONLY,
    DISPOSITION_SOURCE_ACK,
    build_classification_report,
    classify_start,
    first_content_line,
    is_lowercase_nonlist_start,
    is_split_chunk,
    load_chunk_start_acknowledgements,
    matching_acknowledgement,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
START_ACKS = REPO_ROOT / "cdk" / "seed-data" / "chunk-start-acknowledgements.json"


class TestDetectors:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("reuung und Therapie folgen", True),
            ("berufsunfähig ist die Person", True),
            ("Betreuung wird gewährt", False),
            ("## Beiträge", False),
            ("3.1 Leistungen", False),
            ("- ein Listenpunkt", False),
            ("* Listenpunkt", False),
            ("", False),
        ],
    )
    def test_is_lowercase_nonlist_start(self, line, expected):
        assert is_lowercase_nonlist_start(line) is expected

    def test_first_content_line_skips_blank_lines(self):
        assert first_content_line("\n\n  \n## Titel\n\nRest") == "## Titel"

    def test_is_split_chunk(self):
        assert is_split_chunk("flat_section_split")
        assert is_split_chunk("hierarchical_section_split")
        assert not is_split_chunk("flat_section")
        assert not is_split_chunk("glossary_entry")


class TestClassifyStart:
    """The deterministic a/b/c/d decision tree."""

    def test_c_stale_when_regeneration_is_clean(self):
        """Malformed live start that regenerates clean -> stale -> reprocess only."""
        cause, disposition = classify_start(
            regenerated_start_malformed=False,
            regenerated_start_mid_token=False,
            chunk_type="flat_section_split",
            source_truncation=False,
        )
        assert (cause, disposition) == (CAUSE_STALE_ARTIFACT, DISPOSITION_REPROCESS_ONLY)

    def test_a_source_truncation_on_whole_section(self):
        cause, disposition = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=False,
            chunk_type="flat_section",
            source_truncation=True,
        )
        assert (cause, disposition) == (CAUSE_SOURCE_TRUNCATION, DISPOSITION_SOURCE_ACK)

    def test_b_splitter_defect_on_mid_token_split(self):
        """Mid-token split sub-chunk -> splitter defect (must be 0 post-#695)."""
        cause, disposition = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=True,
            chunk_type="flat_section_split",
            source_truncation=False,
        )
        assert (cause, disposition) == (CAUSE_SPLITTER_DEFECT, DISPOSITION_FIX_SPLITTER)

    def test_d_permitted_continuation_at_clean_boundary(self):
        """Lower-case start at a real boundary (no letters lost) -> permitted continuation."""
        cause, disposition = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=False,
            chunk_type="flat_section_split",
            source_truncation=False,
        )
        assert (cause, disposition) == (CAUSE_PERMITTED_CONTINUATION, DISPOSITION_PERMITTED)

    def test_source_truncation_on_split_chunk_is_not_class_a(self):
        """Source-truncation only routes whole-section chunks to (a); a split stays (b)/(d)."""
        cause, _ = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=True,
            chunk_type="flat_section_split",
            source_truncation=True,
        )
        assert cause == CAUSE_SPLITTER_DEFECT

    def test_b_mid_token_on_fallback_chunk_is_never_permitted(self):
        """Mid-token start on a non-``*_split`` chunk is a splitter defect, never permitted (#695)."""
        cause, disposition = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=True,
            chunk_type="flat_paragraph_fallback",
            source_truncation=False,
        )
        assert (cause, disposition) == (CAUSE_SPLITTER_DEFECT, DISPOSITION_FIX_SPLITTER)

    def test_mid_token_takes_precedence_over_source_truncation(self):
        """Mid-token is decided before source truncation so it can never be re-routed to (a)."""
        cause, _ = classify_start(
            regenerated_start_malformed=True,
            regenerated_start_mid_token=True,
            chunk_type="flat_section",
            source_truncation=True,
        )
        assert cause == CAUSE_SPLITTER_DEFECT

    def test_mid_token_is_splitter_defect_even_if_caller_says_not_malformed(self):
        """Mid-token invariant holds standalone; checked first so it can never collapse to (c) stale."""
        cause, disposition = classify_start(
            regenerated_start_malformed=False,
            regenerated_start_mid_token=True,
            chunk_type="flat_section_split",
            source_truncation=False,
        )
        assert (cause, disposition) == (CAUSE_SPLITTER_DEFECT, DISPOSITION_FIX_SPLITTER)


class TestAcknowledgements:
    """Class-(d) acknowledgements loader (mirrors the #680 schema)."""

    def test_loads_valid_empty_file(self, tmp_path):
        path = tmp_path / "acks.json"
        path.write_text('{"version": 1, "acknowledgements": []}', encoding="utf-8")
        assert load_chunk_start_acknowledgements(path) == []

    def test_rejects_wrong_version(self, tmp_path):
        path = tmp_path / "acks.json"
        path.write_text('{"version": 2, "acknowledgements": []}', encoding="utf-8")
        with pytest.raises(ValueError, match="version=1"):
            load_chunk_start_acknowledgements(path)

    def test_rejects_missing_required_field(self, tmp_path):
        path = tmp_path / "acks.json"
        path.write_text(
            json.dumps({"version": 1, "acknowledgements": [{"id": "d1", "source": "x", "passage_prefix": "y"}]}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="missing"):
            load_chunk_start_acknowledgements(path)

    def test_shipped_artifact_is_valid(self):
        payload = json.loads(START_ACKS.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["acknowledgements"] == []
        assert load_chunk_start_acknowledgements(START_ACKS) == []

    def test_matching_acknowledgement_by_source_and_prefix(self):
        acks = [{"id": "d1", "source": "104.xml", "passage_prefix": "sunfähig", "rationale": "r"}]
        match = matching_acknowledgement("104.xml", "sunfähig sind und ...", acks)
        assert match is not None
        assert match["id"] == "d1"
        assert matching_acknowledgement("104.xml", "andere Passage", acks) is None
        assert matching_acknowledgement("other.xml", "sunfähig ...", acks) is None


class TestClassificationReport:
    def _finding(self, cause, source_key="104.xml", first_line="sunfähig sind"):
        return {
            "source_key": source_key,
            "first_content_line": first_line,
            "pipeline": "DITA_XML_PROCESSING",
            "chunk_type": "flat_section_split",
            "section_title": "Abschnitt",
            "cause": cause,
        }

    def test_all_stale_passes(self):
        report = build_classification_report([self._finding(CAUSE_STALE_ARTIFACT)])
        assert report["status"] == "passed"
        assert report["summary"] == {"total": 1, "unresolved": 0, "by_cause": {CAUSE_STALE_ARTIFACT: 1}}

    def test_splitter_defect_is_always_unresolved(self):
        report = build_classification_report([self._finding(CAUSE_SPLITTER_DEFECT)])
        assert report["status"] == "failed"
        assert report["summary"]["unresolved"] == 1

    def test_source_truncation_resolved_only_when_acknowledged(self):
        finding = self._finding(CAUSE_SOURCE_TRUNCATION)
        without = build_classification_report([finding])
        assert without["summary"]["unresolved"] == 1

        ack = {"id": "a1", "rule": "x", "source": "104.xml", "passage_prefix": "sunfähig", "rationale": "r"}
        with_ack = build_classification_report([finding], source_acknowledgements=[ack])
        assert with_ack["summary"]["unresolved"] == 0
        assert with_ack["findings"][0]["resolved"] is True

    def test_permitted_continuation_resolved_only_when_acknowledged(self):
        finding = self._finding(CAUSE_PERMITTED_CONTINUATION)
        without = build_classification_report([finding])
        assert without["summary"]["unresolved"] == 1

        ack = {"id": "d1", "source": "104.xml", "passage_prefix": "sunfähig", "rationale": "r"}
        with_ack = build_classification_report([finding], start_acknowledgements=[ack])
        assert with_ack["summary"]["unresolved"] == 0

    def test_nothing_is_dropped(self):
        findings = [
            self._finding(CAUSE_STALE_ARTIFACT),
            self._finding(CAUSE_SPLITTER_DEFECT),
            self._finding(CAUSE_PERMITTED_CONTINUATION),
        ]
        report = build_classification_report(findings)
        assert report["summary"]["total"] == 3
        assert len(report["findings"]) == 3
