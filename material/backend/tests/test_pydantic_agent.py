from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.agents.agent import (
    AgentResponse,
    create_agent,
    normalize_citations,
    run_agent,
    run_agent_async,
)
from backend_orchestrator.tools.pydantic_tools import _safe_eval, calculator_pydantic


class TestCreateAgent:
    @patch("backend_orchestrator.agents.agent.get_config")
    @patch("backend_orchestrator.agents.agent.create_bedrock_model")
    @patch("backend_orchestrator.agents.agent.Agent")
    def test_create_agent(self, mock_agent_cls, mock_create_model, mock_get_config):
        mock_model = MagicMock()
        mock_create_model.return_value = mock_model

        mock_config = MagicMock()
        mock_config.bedrock_model_id = "test-model"
        mock_config.aws_region = "eu-central-1"
        mock_get_config.return_value = mock_config

        agent = create_agent()

        mock_create_model.assert_called_with("test-model", region="eu-central-1")
        mock_agent_cls.assert_called_once()
        assert agent == mock_agent_cls.return_value


class TestRunAgent:
    def _mock_agent_result(self, answer="Test response", sources=None):
        deps = MagicMock()
        deps.sources = sources or []
        deps.last_retrieval_query = ""
        result = MagicMock()
        result.output = AgentResponse(answer=answer, cited_source_indices=[])
        result.usage.return_value.requests = 1
        result.usage.return_value.total_tokens = 50
        agent = MagicMock()
        agent.run_sync.return_value = result
        return agent, deps

    @patch("backend_orchestrator.agents.agent.AgentDeps")
    def test_run_agent(self, mock_deps_cls):
        agent, deps = self._mock_agent_result(
            answer="Test response",
            sources=[{"sourceName": "doc1"}, {"sourceName": "doc2"}],
        )
        mock_deps_cls.return_value = deps

        response = run_agent(agent, "Hello")

        assert response.result == "Test response"
        assert len(response.sources) == 2

    @patch("backend_orchestrator.agents.agent.AgentDeps")
    def test_run_agent_with_message_history(self, mock_deps_cls):
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

        agent, deps = self._mock_agent_result(answer="Follow-up response")
        mock_deps_cls.return_value = deps

        history = [
            ModelRequest(parts=[UserPromptPart(content="First question")]),
            ModelResponse(parts=[TextPart(content="First answer")]),
        ]

        response = run_agent(agent, "Follow-up", message_history=history)

        call_kwargs = agent.run_sync.call_args[1]
        assert call_kwargs["message_history"] == history
        assert response.result == "Follow-up response"

    @patch("backend_orchestrator.agents.agent.AgentDeps")
    def test_run_agent_without_history(self, mock_deps_cls):
        agent, deps = self._mock_agent_result(answer="Response")
        mock_deps_cls.return_value = deps

        response = run_agent(agent, "Hello")

        call_kwargs = agent.run_sync.call_args[1]
        assert call_kwargs.get("message_history") is None
        assert response.result == "Response"

    @patch("backend_orchestrator.agents.agent.AgentDeps")
    def test_run_agent_failure(self, mock_deps_cls):
        mock_deps_cls.return_value = MagicMock(sources=[])
        mock_agent = MagicMock()
        mock_agent.run_sync.side_effect = Exception("Bedrock unavailable")

        with pytest.raises(Exception, match="Bedrock unavailable"):
            run_agent(mock_agent, "Hello")

    def test_run_agent_with_seed_sources(self):
        """Seeded sources are citable; only cited ones are surfaced."""
        seeds = [
            {"sourceIndex": 1, "title": "Altersrente", "brochureNumber": "BR-1", "content": "snippet 1"},
            {"sourceIndex": 2, "title": "Rentenlexikon", "brochureNumber": "BR-2", "content": "snippet 2"},
        ]

        mock_result = MagicMock()
        mock_result.output = AgentResponse(answer="Antwort [1].", cited_source_indices=[1])
        mock_result.usage.return_value.requests = 1
        mock_result.usage.return_value.total_tokens = 50
        agent = MagicMock()
        agent.run_sync.return_value = mock_result

        response = run_agent(agent, "und wenn ich Lehrer bin?", seed_sources=seeds)

        deps = agent.run_sync.call_args[1]["deps"]
        assert [s["sourceIndex"] for s in deps.sources[:2]] == [1, 2]
        assert len(response.sources) == 1
        assert response.sources[0]["brochureNumber"] == "BR-1"
        assert [s["brochureNumber"] for s in response.all_sources] == ["BR-1"]

    @pytest.mark.asyncio
    async def test_run_agent_async_seeds_and_separates_sources(self):
        """Async run accepts history + seeds and keeps un-cited seeds out of the output."""
        from backend_orchestrator.tools.kb_retrieval import AgentDeps

        seed = {"sourceIndex": 1, "title": "Seed Brochure", "content": "seed"}
        retrieved = {"sourceIndex": 2, "title": "New Brochure", "content": "new"}

        async def run_impl(message, deps: AgentDeps, message_history=None, usage_limits=None):
            deps.sources.append(retrieved)
            result = MagicMock()
            result.output = AgentResponse(answer="Antwort ohne Zitat", cited_source_indices=[])
            result.usage.return_value = MagicMock(
                requests=1, total_tokens=10, cache_read_tokens=0, cache_write_tokens=0
            )
            return result

        agent = MagicMock()
        agent.run = run_impl

        out = await run_agent_async(agent, "Folgefrage", message_history=[MagicMock()], seed_sources=[seed])

        all_titles = [s["title"] for s in out.all_sources]
        used_titles = [s["title"] for s in out.sources]
        assert "Seed Brochure" not in all_titles
        assert "New Brochure" in all_titles
        assert "Seed Brochure" not in used_titles


class TestPydanticTools:
    def test_calculator_pydantic(self):
        ctx = MagicMock()
        assert calculator_pydantic(ctx, "2+2") == "4"
        assert calculator_pydantic(ctx, "10*5") == "50"
        assert "Error" in calculator_pydantic(ctx, "2/0")


class TestSafeEval:
    def test_basic_operations(self):
        assert _safe_eval("2+2") == 4
        assert _safe_eval("10-3") == 7
        assert _safe_eval("4*5") == 20
        assert _safe_eval("20/4") == 5
        assert _safe_eval("10%3") == 1

    def test_decimals(self):
        assert _safe_eval("2.5+2.5") == 5
        assert _safe_eval("10.0/4") == 2.5

    def test_parentheses(self):
        assert _safe_eval("(2+3)*4") == 20
        assert _safe_eval("2*(3+4)") == 14
        assert _safe_eval("((2+3))") == 5

    def test_negative_numbers(self):
        assert _safe_eval("-5+3") == -2
        assert _safe_eval("5+-3") == 2

    def test_complex_expression(self):
        assert _safe_eval("2+3*4") == 14
        assert _safe_eval("(2+3)*(4-1)") == 15

    def test_division_by_zero(self):
        with pytest.raises(ValueError, match="Division by zero"):
            _safe_eval("5/0")

    def test_modulo_by_zero(self):
        with pytest.raises(ValueError, match="Modulo by zero"):
            _safe_eval("5%0")


class TestRunAgentInvalidIndexFallback:

    @patch("backend_orchestrator.agents.agent.AgentDeps")
    def test_invalid_cited_index_stripped_from_text(self, mock_deps_cls):
        sources = [
            {"sourceIndex": 1, "brochureNumber": "BR-1", "content": "c1"},
            {"sourceIndex": 2, "brochureNumber": "BR-2", "content": "c2"},
        ]
        mock_deps_cls.return_value = MagicMock(sources=sources, last_retrieval_query="")

        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = AgentResponse(answer="Answer [99] here.", cited_source_indices=[99])
        mock_result.usage.return_value.requests = 1
        mock_result.usage.return_value.total_tokens = 50
        mock_agent.run_sync.return_value = mock_result

        response = run_agent(mock_agent, "question")

        assert "[99]" not in response.result
        assert len(response.sources) == 2


class TestNormalizeCitations:
    def _source(self, source_index: int, brochure: str, content: str = "") -> dict:
        return {"sourceIndex": source_index, "brochureNumber": brochure, "content": content}

    def test_empty_sources(self):
        sources, text = normalize_citations([], "Some text [1]")
        assert sources == []
        assert text == "Some text [1]"

    def test_no_dedup_needed(self):
        sources = [self._source(1, "BR-1"), self._source(2, "BR-2")]
        result_sources, result_text = normalize_citations(sources, "See [1] and [2].")
        assert len(result_sources) == 2
        assert result_sources[0]["sourceIndex"] == 1
        assert result_sources[1]["sourceIndex"] == 2
        assert result_text == "See [1] and [2]."

    def test_dedup_by_brochure_number(self):
        """Chunks from the same brochure are merged; adjacent duplicate markers collapsed."""
        sources = [
            self._source(1, "BR-42", "chunk A"),
            self._source(2, "BR-42", "chunk B"),
            self._source(3, "BR-99", "chunk C"),
        ]
        result_sources, result_text = normalize_citations(sources, "See [1], [2], and [3].")
        assert len(result_sources) == 2
        assert result_sources[0]["sourceIndex"] == 1
        assert result_sources[1]["sourceIndex"] == 2
        assert result_text == "See [1], and [2]."

    def test_adjacent_duplicate_markers_collapsed(self):
        sources = [self._source(1, "BR-1"), self._source(2, "BR-1")]
        _, result_text = normalize_citations(sources, "Info [1][2] here.")
        assert result_text == "Info [1] here."

    def test_index_remapping_in_text(self):
        sources = [self._source(3, "BR-1"), self._source(7, "BR-2")]
        _, result_text = normalize_citations(sources, "Info [3] and more [7].")
        assert result_text == "Info [1] and more [2]."

    def test_unknown_index_left_unchanged(self):
        sources = [self._source(1, "BR-1")]
        _, result_text = normalize_citations(sources, "Text [1] and dangling [99].")
        assert "[1]" in result_text
        assert "[99]" in result_text

    def test_content_merged_for_same_brochure(self):
        sources = [self._source(1, "BR-1", "first"), self._source(2, "BR-1", "second")]
        result_sources, _ = normalize_citations(sources, "")
        assert len(result_sources) == 1
        assert "first" in result_sources[0]["content"]
        assert "second" in result_sources[0]["content"]
