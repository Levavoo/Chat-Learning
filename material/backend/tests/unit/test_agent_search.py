"""Tests for agent-based document search: tools, meta parsing, and wiring."""

import json
import unittest
from unittest.mock import MagicMock, mock_open, patch

from backend_orchestrator.tools import agent_search
from backend_orchestrator.tools.agent_search import _load_document, fetch_section, list_sections, read_index
from backend_orchestrator.tools.pydantic_tools import _parse_agent_search_meta


class TestReadIndex(unittest.TestCase):
    def setUp(self):
        agent_search._cached_index = None
        agent_search._cached_docs = {}

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_read_index_from_local(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_config.agent_search_index_prefix = "agent-search-index/"
        mock_get_config.return_value = mock_config

        index_data = '{"documents": [{"doc_id": "B01", "title": "Test"}]}'
        with patch("builtins.open", mock_open(read_data=index_data)):
            result = read_index()

        self.assertEqual(result, index_data)
        parsed = json.loads(result)
        self.assertEqual(parsed["documents"][0]["doc_id"], "B01")

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_read_index_from_s3(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = "test-bucket"
        mock_config.agent_search_index_prefix = "idx/"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        index_data = '{"documents": []}'
        with patch("backend_orchestrator.tools.agent_search._load_from_s3", return_value=index_data) as mock_s3:
            result = read_index()

        mock_s3.assert_called_once_with("test-bucket", "idx/index.json", "eu-central-1")
        self.assertEqual(result, index_data)

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_read_index_caches_result(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        index_data = '{"documents": []}'
        with patch("builtins.open", mock_open(read_data=index_data)):
            read_index()
            result = read_index()

        self.assertEqual(result, index_data)
        mock_get_config.assert_called_once()

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_read_index_returns_empty_on_error(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        with patch("builtins.open", side_effect=FileNotFoundError("not found")):
            result = read_index()

        self.assertEqual(result, '{"documents": []}')


class TestFetchDocument(unittest.TestCase):
    def setUp(self):
        agent_search._cached_index = None
        agent_search._cached_docs = {}

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_document_from_local(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_config.agent_search_index_prefix = "agent-search-index/"
        mock_get_config.return_value = mock_config

        doc_data = '{"doc_id": "B16", "sections": []}'
        with patch("builtins.open", mock_open(read_data=doc_data)):
            result = _load_document("B16")

        self.assertEqual(result, doc_data)

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_document_from_s3(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = "test-bucket"
        mock_config.agent_search_index_prefix = "idx/"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        doc_data = '{"doc_id": "B16"}'
        with patch("backend_orchestrator.tools.agent_search._load_from_s3", return_value=doc_data) as mock_s3:
            result = _load_document("B16")

        mock_s3.assert_called_once_with("test-bucket", "idx/documents/B16.json", "eu-central-1")
        self.assertEqual(result, doc_data)

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_document_caches_result(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = '{"doc_id": "B16"}'
        with patch("builtins.open", mock_open(read_data=doc_data)):
            _load_document("B16")
            result = _load_document("B16")

        self.assertEqual(result, doc_data)
        mock_get_config.assert_called_once()

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_document_returns_error_on_missing(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        with patch("builtins.open", side_effect=FileNotFoundError("not found")):
            result = _load_document("MISSING")

        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("MISSING", parsed["error"])


class TestListSections(unittest.TestCase):
    def setUp(self):
        agent_search._cached_index = None
        agent_search._cached_docs = {}

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_list_sections_returns_titles_with_indices(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = json.dumps({
            "doc_id": "B01",
            "title": "Test Doc",
            "sections": [
                {"title": "Einleitung", "content": "..."},
                {"title": "Hauptteil", "content": "..."},
            ],
        })
        with patch("builtins.open", mock_open(read_data=doc_data)):
            result = json.loads(list_sections("B01"))

        self.assertEqual(result["doc_id"], "B01")
        self.assertEqual(len(result["sections"]), 2)
        self.assertEqual(result["sections"][0], {"index": 0, "title": "Einleitung"})
        self.assertEqual(result["sections"][1], {"index": 1, "title": "Hauptteil"})

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_list_sections_invalid_doc_id(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        result = json.loads(list_sections("../etc/passwd"))
        self.assertIn("error", result)


class TestFetchSection(unittest.TestCase):
    def setUp(self):
        agent_search._cached_index = None
        agent_search._cached_docs = {}
        agent_search.fetched_docs_context.set(None)

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_section_returns_content(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = json.dumps({
            "doc_id": "B01",
            "title": "Test",
            "edition": "1",
            "published": "2024",
            "sections": [{"title": "Sec A", "content": "Content A"}, {"title": "Sec B", "content": "Content B"}],
        })
        with patch("builtins.open", mock_open(read_data=doc_data)):
            result = json.loads(fetch_section("B01", 1))

        self.assertEqual(result["section_title"], "Sec B")
        self.assertEqual(result["content"], "Content B")
        self.assertEqual(result["section_index"], 1)

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_section_out_of_bounds(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = json.dumps({"doc_id": "B01", "sections": [{"title": "A", "content": "a"}]})
        with patch("builtins.open", mock_open(read_data=doc_data)):
            result = json.loads(fetch_section("B01", 5))

        self.assertIn("error", result)
        self.assertIn("Verfügbar: 0-0", result["error"])

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_section_empty_sections(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = json.dumps({"doc_id": "B01", "sections": []})
        with patch("builtins.open", mock_open(read_data=doc_data)):
            result = json.loads(fetch_section("B01", 0))

        self.assertIn("error", result)
        self.assertIn("keine Abschnitte", result["error"])

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_section_populates_context(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        doc_data = json.dumps({
            "doc_id": "B01",
            "title": "Test",
            "edition": "",
            "published": "",
            "category": "reha",
            "sections": [{"title": "Sec", "content": "text"}],
        })
        with patch("builtins.open", mock_open(read_data=doc_data)):
            fetch_section("B01", 0)

        ctx = agent_search.fetched_docs_context.get()
        assert ctx is not None
        self.assertEqual(len(ctx), 1)
        self.assertEqual(ctx[0]["doc_id"], "B01")
        self.assertEqual(ctx[0]["content"], "text")

    @patch("backend_orchestrator.tools.agent_search.get_config")
    def test_fetch_section_invalid_doc_id(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.agent_search_index_bucket = ""
        mock_get_config.return_value = mock_config

        result = json.loads(fetch_section("../../etc/passwd", 0))
        self.assertIn("error", result)


class TestParseAgentSearchMeta(unittest.TestCase):
    def test_parse_single_meta_line(self):
        text = "META|1|B16|Erwerbsminderungsrente|19. Auflage|7/2024|Volle Erwerbsminderung"
        sources = _parse_agent_search_meta(text)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["brochureNumber"], "B16")
        self.assertEqual(sources[0]["title"], "Erwerbsminderungsrente")
        self.assertEqual(sources[0]["publishingDate"], "7/2024")
        self.assertEqual(sources[0]["sectionTitle"], "Volle Erwerbsminderung")
        self.assertEqual(sources[0]["sourceIndex"], 1)

    def test_parse_multiple_meta_lines(self):
        text = (
            "[Source 1: Broschüre A]\nInhalt A\n"
            "[Source 2: Broschüre B]\nInhalt B\n"
            "META|1|B16|Broschüre A|19. Auflage|7/2024|Abschnitt A\n"
            "META|2|B17|Broschüre B|20. Auflage|8/2024|Abschnitt B"
        )
        sources = _parse_agent_search_meta(text)

        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["brochureNumber"], "B16")
        self.assertEqual(sources[1]["brochureNumber"], "B17")

    def test_parse_no_meta_lines(self):
        text = "Keine relevanten Dokumente gefunden."
        sources = _parse_agent_search_meta(text)
        self.assertEqual(sources, [])

    def test_parse_meta_with_empty_optional_fields(self):
        text = "META|1|F01|Faltblatt|||Abschnitt"
        sources = _parse_agent_search_meta(text)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["edition"], "")
        self.assertEqual(sources[0]["publishingDate"], "")


class TestGetPydanticToolsSearchMode(unittest.TestCase):
    @patch("backend_orchestrator.tools.pydantic_tools.get_config")
    def test_rag_mode_returns_kb_search_tool(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.search_mode = "rag"
        mock_get_config.return_value = mock_config

        from backend_orchestrator.tools.pydantic_tools import get_pydantic_tools

        tools = get_pydantic_tools()
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        self.assertIn("search_knowledge_base_pydantic", tool_names)
        self.assertNotIn("agent_search_pydantic", tool_names)

    @patch("backend_orchestrator.tools.pydantic_tools.get_config")
    def test_agent_mode_returns_agent_search_tool(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.search_mode = "agent"
        mock_get_config.return_value = mock_config

        from backend_orchestrator.tools.pydantic_tools import get_pydantic_tools

        tools = get_pydantic_tools()
        tool_names = [getattr(t, "__name__", str(t)) for t in tools]
        self.assertIn("agent_search_pydantic", tool_names)
        self.assertNotIn("search_knowledge_base_pydantic", tool_names)


class TestCreateSearchAgent(unittest.TestCase):
    def setUp(self):
        import backend_orchestrator.agents.agent as agent_mod

        agent_mod._search_agent = None

    @patch("backend_orchestrator.agents.agent.Agent")
    @patch("backend_orchestrator.agents.agent.create_bedrock_model")
    @patch("backend_orchestrator.agents.agent.get_config")
    def test_create_search_agent(self, mock_get_config, mock_create_model, mock_agent_cls):
        mock_config = MagicMock()
        mock_config.agent_search_model_id = "eu.amazon.nova-2-lite-v1:0"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config
        mock_create_model.return_value = MagicMock()

        from backend_orchestrator.agents.agent import create_search_agent

        create_search_agent()

        mock_create_model.assert_called_once_with("eu.amazon.nova-2-lite-v1:0", region="eu-central-1")
        mock_agent_cls.assert_called_once()
        call_kwargs = mock_agent_cls.call_args[1]
        self.assertEqual(len(call_kwargs["tools"]), 3)

    @patch("backend_orchestrator.agents.agent.Agent")
    @patch("backend_orchestrator.agents.agent.create_bedrock_model")
    @patch("backend_orchestrator.agents.agent.get_config")
    def test_create_search_agent_caches(self, mock_get_config, mock_create_model, mock_agent_cls):
        mock_config = MagicMock()
        mock_config.agent_search_model_id = "eu.amazon.nova-2-lite-v1:0"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config
        mock_create_model.return_value = MagicMock()

        from backend_orchestrator.agents.agent import create_search_agent

        agent1 = create_search_agent()
        agent2 = create_search_agent()

        self.assertIs(agent1, agent2)
        mock_agent_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
