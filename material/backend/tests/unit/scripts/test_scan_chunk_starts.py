"""Tests for the read-only chunk-start audit script (#695)."""

import json

import pytest

import scripts.scan_chunk_starts as audit
from etl.chunk_start_quality import (
    CAUSE_PERMITTED_CONTINUATION,
    CAUSE_SOURCE_TRUNCATION,
    CAUSE_SPLITTER_DEFECT,
    CAUSE_STALE_ARTIFACT,
)
from scripts.scan_chunk_starts import RegenChunk


def _regen(first_line, *, mid_token, chunk_type="flat_section_split", section="Abschnitt"):
    return RegenChunk(
        name="doc/doc_0001",
        chunk_type=chunk_type,
        section_title=section,
        first_line=first_line,
        mid_token=mid_token,
    )


class TestAuditFromSource:
    """audit_from_source flags lower-case starts and classifies them."""

    def test_classifies_mid_token_and_permitted(self, tmp_path, monkeypatch):
        (tmp_path / "doc.xml").write_text("<topic/>", encoding="utf-8")
        chunks = [
            _regen("Betreuung wird gewährt", mid_token=False),
            _regen("reuung und Therapie", mid_token=True),
            _regen("berufsunfähig bleibt", mid_token=False),
        ]
        monkeypatch.setattr(audit, "regenerate", lambda _p: ("M", chunks))
        monkeypatch.setattr(audit, "_source_truncation", lambda _p: False)

        findings = audit.audit_from_source(tmp_path)

        causes = sorted(f["cause"] for f in findings)
        assert causes == sorted([CAUSE_SPLITTER_DEFECT, CAUSE_PERMITTED_CONTINUATION])
        assert all(f["pipeline"] == "DITA_XML_PROCESSING" for f in findings)

    def test_whole_section_truncation_is_class_a(self, tmp_path, monkeypatch):
        (tmp_path / "doc.xml").write_text("<topic/>", encoding="utf-8")
        chunks = [_regen("hausarzt beifügen und ...", mid_token=False, chunk_type="flat_section")]
        monkeypatch.setattr(audit, "regenerate", lambda _p: ("M", chunks))
        monkeypatch.setattr(audit, "_source_truncation", lambda _p: True)

        findings = audit.audit_from_source(tmp_path)

        assert [f["cause"] for f in findings] == [CAUSE_SOURCE_TRUNCATION]

    def test_mid_token_fallback_chunk_is_splitter_defect(self, tmp_path, monkeypatch):
        """Mid-token flat_paragraph_fallback is splitter_defect, not permitted (#695)."""
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4 stub")
        chunks = [_regen("reuung und Therapie", mid_token=True, chunk_type="flat_paragraph_fallback")]
        monkeypatch.setattr(audit, "regenerate", lambda _p: ("M", chunks))
        monkeypatch.setattr(audit, "_source_truncation", lambda _p: False)

        findings = audit.audit_from_source(tmp_path)

        assert [f["cause"] for f in findings] == [CAUSE_SPLITTER_DEFECT]
        assert findings[0]["pipeline"] == "PDF_PROCESSING"

    def test_regeneration_error_is_recorded_not_dropped(self, tmp_path, monkeypatch):
        (tmp_path / "doc.xml").write_text("<topic/>", encoding="utf-8")

        def _boom(_p):
            raise RuntimeError("bad source")

        monkeypatch.setattr(audit, "regenerate", _boom)
        findings = audit.audit_from_source(tmp_path)
        assert len(findings) == 1
        assert findings[0]["cause"] == "unclassified_regeneration_error"


class TestChunkStartAlignment:
    def test_short_word_head_is_not_a_false_mid_token(self):
        """Whole-word 'der' start must not be a false mid-token flag (#695)."""
        markdown = "Das gilt oder auch nicht.\n\nbei der\n\nder folgende Absatz steht hier klar."
        content = "der folgende Absatz steht hier klar."
        assert audit._chunk_start_mid_token(markdown, content) is False

    def test_real_mid_token_start_is_detected(self):
        markdown = "Vorwort zur Betreuung und Therapie steht hier."
        content = "reuung und Therapie steht hier."
        assert audit._chunk_start_mid_token(markdown, content) is True

    def test_absent_content_is_not_mid_token(self):
        assert audit._chunk_start_mid_token("some markdown text", "unrelated content here") is False


class TestRenderMarkdown:
    def test_renders_table_and_escapes_pipes(self):
        report = {
            "summary": {"total": 1, "unresolved": 1, "by_cause": {CAUSE_SPLITTER_DEFECT: 1}},
            "findings": [
                {
                    "source_key": "104.xml",
                    "first_content_line": "a | b fragment",
                    "pipeline": "DITA_XML_PROCESSING",
                    "chunk_type": "flat_section_split",
                    "cause": CAUSE_SPLITTER_DEFECT,
                    "disposition": "fix_splitter",
                    "resolved": False,
                }
            ],
        }
        rendered = audit._render_markdown(report)
        assert "| 104.xml |" in rendered
        assert "a \\| b fragment" in rendered
        assert "| NO |" in rendered


class TestMainCli:
    def test_from_source_nonzero_on_unresolved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            audit,
            "audit_from_source",
            lambda _dir: [
                {
                    "source_key": "104.xml",
                    "first_content_line": "reuung",
                    "pipeline": "DITA_XML_PROCESSING",
                    "chunk_type": "flat_section_split",
                    "section_title": "s",
                    "cause": CAUSE_SPLITTER_DEFECT,
                    "disposition": "fix_splitter",
                }
            ],
        )
        report_path = tmp_path / "r.json"
        exit_code = audit.main(["--from-source", "--report", str(report_path)])
        assert exit_code == 1
        assert json.loads(report_path.read_text(encoding="utf-8"))["summary"]["unresolved"] == 1

    def test_from_source_zero_when_all_stale(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            audit,
            "audit_from_source",
            lambda _dir: [
                {
                    "source_key": "104.xml",
                    "first_content_line": "ersicherungsträger",
                    "pipeline": "DITA_XML_PROCESSING",
                    "chunk_type": "flat_section_split",
                    "section_title": "s",
                    "cause": CAUSE_STALE_ARTIFACT,
                    "disposition": "reprocess_only",
                }
            ],
        )
        assert audit.main(["--from-source"]) == 0

    def test_requires_a_mode(self):
        with pytest.raises(SystemExit):
            audit.main([])
