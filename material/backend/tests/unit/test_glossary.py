import json
from pathlib import Path

import pytest

from backend_orchestrator import glossary
from backend_orchestrator.glossary import (
    GlossaryEntry,
    build_glossary_prompt_context,
    load_glossary,
)

pytestmark = pytest.mark.unit

SAMPLE_ENTRIES = [
    GlossaryEntry(term="Grundrente", definition="Beschreibung für den Grundrentenzuschlag."),
    GlossaryEntry(term="IRENA", definition="Intensivierte Reha-Nachsorge."),
]


class TestGlossaryPackageLayout:
    """glossary.json must sit at the package-relative path the Lambda layout expects."""

    def test_glossary_file_exists_in_package(self):
        """glossary.json must exist next to glossary.py so it's bundled in the Lambda image."""
        from backend_orchestrator.glossary import _GLOSSARY_PATH

        assert _GLOSSARY_PATH.exists(), (
            f"glossary.json not found at {_GLOSSARY_PATH}. "
            "It must live in backend/src/backend_orchestrator/data/ to be deployed with the Lambda."
        )

    def test_glossary_path_is_package_relative(self):
        """Path must use parent (not parents[N]) to work in /var/task/ Lambda layout."""
        import inspect

        from backend_orchestrator import glossary as mod

        module_dir = Path(inspect.getfile(mod)).parent
        assert glossary._GLOSSARY_PATH.is_relative_to(module_dir), (
            f"_GLOSSARY_PATH ({glossary._GLOSSARY_PATH}) is not relative to package dir ({module_dir})"
        )


class TestLoadGlossary:
    def setup_method(self):
        glossary._glossary_cache = None

    def test_loads_from_default_path(self):
        result = load_glossary()
        assert len(result) == 24
        assert all(isinstance(e, GlossaryEntry) for e in result)
        assert result[0].term == "Rentnerprivileg"

    def test_caches_result(self):
        result1 = load_glossary()
        result2 = load_glossary()
        assert result1 is result2

    def test_file_not_found_returns_empty(self, tmp_path):
        glossary._glossary_cache = None
        result = load_glossary(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_does_not_cache_on_error(self, tmp_path):
        """Transient error must not cache empty list permanently."""
        glossary._glossary_cache = None
        load_glossary(str(tmp_path / "nonexistent.json"))
        assert glossary._glossary_cache is None

    def test_invalid_json_returns_empty(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        glossary._glossary_cache = None
        result = load_glossary(str(bad_file))
        assert result == []

    def test_skips_entries_missing_fields(self, tmp_path):
        data = [{"term": "Valid", "definition": "OK"}, {"term": "NoDefinition"}, {"other": "field"}]
        f = tmp_path / "partial.json"
        f.write_text(json.dumps(data))
        glossary._glossary_cache = None
        result = load_glossary(str(f))
        assert len(result) == 1
        assert result[0].term == "Valid"


class TestBuildGlossaryPromptContext:
    def test_contains_header_and_footer(self):
        result = build_glossary_prompt_context(SAMPLE_ENTRIES)
        assert result.startswith("[GLOSSAR-KONTEXT]")
        assert result.endswith("[/GLOSSAR-KONTEXT]")

    def test_contains_all_entries(self):
        result = build_glossary_prompt_context(SAMPLE_ENTRIES)
        assert "Grundrente" in result
        assert "Grundrentenzuschlag" in result
        assert "IRENA" in result
        assert "Intensivierte Reha-Nachsorge" in result

    def test_empty_list(self):
        result = build_glossary_prompt_context([])
        assert "[GLOSSAR-KONTEXT]" in result
        assert "[/GLOSSAR-KONTEXT]" in result
