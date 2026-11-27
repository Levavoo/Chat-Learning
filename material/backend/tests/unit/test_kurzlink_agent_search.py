"""Tests for Kurzlink (brochure_url_short) in the agent-search path (#502)."""

import importlib.util
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Load generate_agent_search_index as a module (it's a script, not an installed package);
# importlib.util avoids sys.path pollution and works with static type checkers.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location(
    "generate_agent_search_index", _SCRIPTS_DIR / "generate_agent_search_index.py"
)
assert _spec and _spec.loader
_gen_module = importlib.util.module_from_spec(_spec)
sys.modules["generate_agent_search_index"] = _gen_module
_spec.loader.exec_module(_gen_module)

script_derive_short_url = _gen_module._derive_short_brochure_url
write_documents = _gen_module.write_documents
write_index = _gen_module.write_index

from backend_orchestrator.tools.pydantic_tools import (  # noqa: E402
    _derive_short_brochure_url as tools_derive_short_url,
)
from backend_orchestrator.tools.pydantic_tools import (  # noqa: E402
    _parse_agent_search_meta,
)

class TestDeriveShortBrochureUrlScript:
    def test_valid_single_letter_prefix(self):
        assert script_derive_short_url("B02") == "https://www.deutsche-rentenversicherung.de/B02"

    def test_valid_double_letter_prefix(self):
        assert script_derive_short_url("FB28") == "https://www.deutsche-rentenversicherung.de/FB28"

    def test_valid_merkblatt_v_prefix(self):
        assert script_derive_short_url("V0090") == "https://www.deutsche-rentenversicherung.de/V0090"

    def test_valid_merkblatt_g_prefix(self):
        assert script_derive_short_url("G0103") == "https://www.deutsche-rentenversicherung.de/G0103"

    def test_valid_merkblatt_r_prefix(self):
        assert script_derive_short_url("R0101") == "https://www.deutsche-rentenversicherung.de/R0101"

    def test_invalid_with_suffix(self):
        assert script_derive_short_url("B38_v2") is None

    def test_invalid_faq_id(self):
        assert script_derive_short_url("FAQ_DRV_Web") is None

    def test_invalid_lowercase(self):
        assert script_derive_short_url("b02") is None

    def test_invalid_too_few_digits(self):
        assert script_derive_short_url("B1") is None

    def test_invalid_too_many_digits(self):
        assert script_derive_short_url("B12345") is None

    def test_empty_string(self):
        assert script_derive_short_url("") is None


class TestDeriveShortBrochureUrlTools:
    def test_valid_id(self):
        assert tools_derive_short_url("B16") == "https://www.deutsche-rentenversicherung.de/B16"

    def test_invalid_id_with_suffix(self):
        assert tools_derive_short_url("B38_v2") is None

    def test_valid_merkblatt(self):
        assert tools_derive_short_url("V0017") == "https://www.deutsche-rentenversicherung.de/V0017"


class TestWriteDocumentsKurzlink:
    def test_valid_id_includes_short_url(self, tmp_path):
        docs = [
            {
                "doc_id": "B02",
                "title": "Hinterbliebenenrente",
                "category": "Rente",
                "edition": "5. Auflage",
                "published": "3/2025",
                "sections": [{"title": "Einleitung", "content": "Text"}],
            }
        ]
        write_documents(docs, tmp_path)
        doc = json.loads((tmp_path / "documents" / "B02.json").read_text())
        assert doc["brochure_url_short"] == "https://www.deutsche-rentenversicherung.de/B02"

    def test_merkblatt_id_includes_short_url(self, tmp_path):
        docs = [
            {
                "doc_id": "V0090",
                "title": "Merkblatt Versicherungsschutz",
                "category": "Merkblatt",
                "edition": "Online",
                "published": "2026-01",
                "sections": [{"title": "S", "content": "C"}],
            }
        ]
        write_documents(docs, tmp_path)
        doc = json.loads((tmp_path / "documents" / "V0090.json").read_text())
        assert doc["brochure_url_short"] == "https://www.deutsche-rentenversicherung.de/V0090"

    def test_invalid_id_produces_empty_url(self, tmp_path):
        docs = [
            {
                "doc_id": "B38_v2",
                "title": "Duplicate doc",
                "category": "Rente",
                "edition": "1",
                "published": "1/25",
                "sections": [{"title": "S", "content": "C"}],
            }
        ]
        write_documents(docs, tmp_path)
        doc = json.loads((tmp_path / "documents" / "B38_v2.json").read_text())
        assert doc["brochure_url_short"] == ""

    def test_invalid_id_logs_warning(self, tmp_path, caplog):
        docs = [
            {
                "doc_id": "FAQ_DRV_Web",
                "title": "FAQ",
                "category": "FAQ",
                "edition": "Online",
                "published": "2026",
                "sections": [{"title": "Q1", "content": "A1"}],
            }
        ]
        with caplog.at_level(logging.WARNING):
            write_documents(docs, tmp_path)
        assert any("FAQ_DRV_Web" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# write_index includes brochure_url_short
# ---------------------------------------------------------------------------


class TestWriteIndexKurzlink:
    def test_main_doc_includes_short_url(self, tmp_path):
        docs = [
            {
                "doc_id": "B05",
                "title": "Krankenversicherung",
                "category": "Rente",
                "edition": "21. Auflage",
                "published": "2/2026",
                "keywords": ["KVdR"],
                "sections": [{"title": "S", "content": "C"}],
                "summary": "Sum",
            }
        ]
        write_index(docs, tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["documents"][0]["brochure_url_short"] == "https://www.deutsche-rentenversicherung.de/B05"

    def test_invalid_main_doc_gets_empty_url(self, tmp_path):
        docs = [
            {
                "doc_id": "B38_v2",
                "title": "Dup",
                "category": "R",
                "edition": "1",
                "published": "1/25",
                "keywords": [],
                "sections": [{"title": "S", "content": "C"}],
                "summary": "",
            }
        ]
        write_index(docs, tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert index["documents"][0]["brochure_url_short"] == ""

    def test_extra_doc_propagates_short_url(self, tmp_path):
        docs_dir = tmp_path / "documents"
        docs_dir.mkdir(parents=True)
        extra_doc = {
            "doc_id": "G0103",
            "title": "Reha-Antrag",
            "category": "Merkblatt",
            "edition": "Online",
            "published": "2026",
            "keywords": ["Reha"],
            "sections": [{"title": "S", "content": "C"}],
            "summary": "Info",
            "brochure_url_short": "https://www.deutsche-rentenversicherung.de/G0103",
        }
        (docs_dir / "G0103.json").write_text(json.dumps(extra_doc), encoding="utf-8")

        write_index([], tmp_path)
        index = json.loads((tmp_path / "index.json").read_text())
        assert len(index["documents"]) == 1
        assert index["documents"][0]["doc_id"] == "G0103"
        assert index["documents"][0]["brochure_url_short"] == "https://www.deutsche-rentenversicherung.de/G0103"


# ---------------------------------------------------------------------------
# _parse_agent_search_meta populates brochureUrl
# ---------------------------------------------------------------------------


class TestParseAgentSearchMetaKurzlink:
    def test_valid_doc_id_produces_url(self):
        text = "META|1|B16|Erwerbsminderungsrente|19. Auflage|7/2024|Volle EM"
        sources = _parse_agent_search_meta(text)
        assert sources[0]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/B16"

    def test_merkblatt_id_produces_url(self):
        text = "META|1|V0090|Versicherungsschutz||2026|Lücken vermeiden"
        sources = _parse_agent_search_meta(text)
        assert sources[0]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/V0090"

    def test_invalid_doc_id_produces_empty_url(self):
        text = "META|1|FAQ_DRV_Web|FAQ|||Frage 1"
        sources = _parse_agent_search_meta(text)
        assert sources[0]["brochureUrl"] == ""

    def test_b38_v2_produces_empty_url(self):
        text = "META|1|B38_v2|Duplicate|1||Section"
        sources = _parse_agent_search_meta(text)
        assert sources[0]["brochureUrl"] == ""
        assert sources[0]["brochureNumber"] == "B38_v2"

    def test_multiple_sources_each_derive_url(self):
        text = "META|1|B02|Hinterbliebene|5|3/2025|Erziehungsrente\nMETA|2|G0103|Reha||2026|Antrag"
        sources = _parse_agent_search_meta(text)
        assert sources[0]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/B02"
        assert sources[1]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/G0103"


class TestFetchedDocsFallbackKurzlink:
    def test_fallback_uses_brochure_url_short_from_doc(self):
        doc_with_url = {
            "doc_id": "V0017",
            "title": "Befreiung Handwerker",
            "edition": "Online",
            "published": "2026",
            "category": "Merkblatt",
            "brochure_url_short": "https://www.deutsche-rentenversicherung.de/V0017",
            "content": "Befreiungsvoraussetzungen...",
        }

        brochure_url = doc_with_url.get("brochure_url_short") or tools_derive_short_url(doc_with_url["doc_id"]) or ""
        assert brochure_url == "https://www.deutsche-rentenversicherung.de/V0017"

    def test_fallback_derives_when_field_missing(self):
        doc_without_url = {
            "doc_id": "B05",
            "title": "Krankenversicherung",
            "edition": "21",
            "published": "2/2026",
            "category": "Rente",
            "content": "KVdR info",
        }

        brochure_url = (
            doc_without_url.get("brochure_url_short") or tools_derive_short_url(doc_without_url["doc_id"]) or ""
        )
        assert brochure_url == "https://www.deutsche-rentenversicherung.de/B05"

    def test_fallback_empty_for_invalid_id(self):
        doc_invalid = {
            "doc_id": "B38_v2",
            "title": "Dup",
            "edition": "",
            "published": "",
            "category": "Rente",
            "content": "text",
        }

        brochure_url = doc_invalid.get("brochure_url_short") or tools_derive_short_url(doc_invalid["doc_id"]) or ""
        assert brochure_url == ""

    def test_fallback_empty_string_field_triggers_derivation(self):
        doc_empty_url = {
            "doc_id": "R0501",
            "title": "Hinterbliebenenrente Antrag",
            "brochure_url_short": "",
            "content": "Antrag...",
        }

        brochure_url = doc_empty_url.get("brochure_url_short") or tools_derive_short_url(doc_empty_url["doc_id"]) or ""
        assert brochure_url == "https://www.deutsche-rentenversicherung.de/R0501"


# ---------------------------------------------------------------------------
# Real fallback code path in agent_search_pydantic (_make_agent_search_tool)
# ---------------------------------------------------------------------------


def _make_fake_agent(fetched_docs: list[dict], output_text: str):
    """Mock search agent whose run_sync populates fetched_docs_context and returns output without META lines."""
    from backend_orchestrator.tools.agent_search import fetched_docs_context

    def fake_run_sync(_query: str):
        fetched_docs_context.set(fetched_docs)
        result = MagicMock()
        result.output = output_text
        return result

    agent = MagicMock()
    agent.run_sync.side_effect = fake_run_sync
    return agent


class TestAgentSearchToolFallbackRealPath:
    """Drive the real fetched-docs fallback branch (output without META lines) with a mocked search agent."""

    def _run_tool(self, fetched_docs: list[dict], output_text: str = "Ergebnis ohne META-Zeilen.") -> list[dict]:
        from backend_orchestrator.tools.pydantic_tools import _make_agent_search_tool

        fake_agent = _make_fake_agent(fetched_docs, output_text)
        with patch("backend_orchestrator.agents.agent.create_search_agent", return_value=fake_agent):
            tool = _make_agent_search_tool()
            ctx = MagicMock()
            ctx.deps.sources = []
            tool(ctx, "beliebige suchanfrage")
            return ctx.deps.sources

    def test_fallback_surfaces_brochure_url_short_field(self):
        docs = [
            {
                "doc_id": "V0017",
                "title": "Befreiung Handwerker",
                "edition": "Online",
                "published": "2026",
                "category": "Merkblatt",
                "brochure_url_short": "https://www.deutsche-rentenversicherung.de/V0017",
                "content": "Befreiungsvoraussetzungen ...",
            }
        ]
        sources = self._run_tool(docs)
        assert len(sources) == 1
        assert sources[0]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/V0017"

    def test_fallback_derives_when_field_absent(self):
        docs = [
            {
                "doc_id": "B05",
                "title": "Krankenversicherung",
                "edition": "21",
                "published": "2/2026",
                "category": "Rente",
                "content": "KVdR info",
            }
        ]
        sources = self._run_tool(docs)
        assert sources[0]["brochureUrl"] == "https://www.deutsche-rentenversicherung.de/B05"

    def test_fallback_empty_for_invalid_doc_id(self):
        docs = [
            {
                "doc_id": "B38_v2",
                "title": "Duplicate",
                "edition": "",
                "published": "",
                "category": "Rente",
                "content": "text",
            }
        ]
        sources = self._run_tool(docs)
        assert sources[0]["brochureUrl"] == ""
        assert sources[0]["brochureNumber"] == "B38_v2"
