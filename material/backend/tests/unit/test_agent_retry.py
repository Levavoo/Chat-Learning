"""Tests for agent retry logic."""

import time
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from pydantic_ai import UnexpectedModelBehavior

from backend_orchestrator.agents.agent import _is_retryable, _run_with_retry


class TestIsRetryable(unittest.TestCase):
    def test_unexpected_model_behavior_is_retryable(self):
        assert _is_retryable(UnexpectedModelBehavior("bad response")) is True

    def test_throttling_exception_is_retryable(self):
        err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "InvokeModel")
        assert _is_retryable(err) is True

    def test_service_unavailable_is_retryable(self):
        err = ClientError({"Error": {"Code": "ServiceUnavailableException", "Message": ""}}, "InvokeModel")
        assert _is_retryable(err) is True

    def test_model_timeout_is_retryable(self):
        err = ClientError({"Error": {"Code": "ModelTimeoutException", "Message": ""}}, "InvokeModel")
        assert _is_retryable(err) is True

    def test_validation_exception_not_retryable(self):
        err = ClientError({"Error": {"Code": "ValidationException", "Message": ""}}, "InvokeModel")
        assert _is_retryable(err) is False

    def test_generic_exception_not_retryable(self):
        assert _is_retryable(ValueError("something")) is False


class TestRunWithRetry(unittest.TestCase):
    def _make_agent(self, side_effects):
        agent = MagicMock()
        agent.run_sync = MagicMock(side_effect=side_effects)
        return agent

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_retries_on_transient_error_then_succeeds(self, mock_sleep):
        mock_result = MagicMock()
        agent = self._make_agent([
            UnexpectedModelBehavior("bad response"),
            mock_result,
        ])

        result = _run_with_retry(agent, "hello", MagicMock(), None, 15, time.monotonic())

        assert result is mock_result
        assert agent.run_sync.call_count == 2
        mock_sleep.assert_called_once_with(1.0)

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_retries_on_throttling_then_succeeds(self, mock_sleep):
        mock_result = MagicMock()
        err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "InvokeModel")
        agent = self._make_agent([err, mock_result])

        result = _run_with_retry(agent, "hello", MagicMock(), None, 15, time.monotonic())

        assert result is mock_result
        assert agent.run_sync.call_count == 2

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_no_retry_when_time_budget_exhausted(self, mock_sleep):
        agent = self._make_agent([UnexpectedModelBehavior("bad response")])
        start_time = time.monotonic() - 21.0

        with self.assertRaises(UnexpectedModelBehavior):
            _run_with_retry(agent, "hello", MagicMock(), None, 15, start_time)

        assert agent.run_sync.call_count == 1
        mock_sleep.assert_not_called()

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_no_retry_on_non_retryable_client_error(self, mock_sleep):
        err = ClientError({"Error": {"Code": "ValidationException", "Message": "bad input"}}, "InvokeModel")
        agent = self._make_agent([err])

        with self.assertRaises(ClientError):
            _run_with_retry(agent, "hello", MagicMock(), None, 15, time.monotonic())

        assert agent.run_sync.call_count == 1
        mock_sleep.assert_not_called()

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_raises_on_second_failure(self, mock_sleep):
        agent = self._make_agent([
            UnexpectedModelBehavior("first"),
            UnexpectedModelBehavior("second"),
        ])

        with self.assertRaises(UnexpectedModelBehavior) as ctx:
            _run_with_retry(agent, "hello", MagicMock(), None, 15, time.monotonic())

        assert "second" in str(ctx.exception)
        assert agent.run_sync.call_count == 2

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_discards_failed_attempt_sources_but_keeps_seeds(self, mock_sleep):
        """Sources collected by the failed attempt are discarded; seeded history sources survive."""
        from backend_orchestrator.tools.kb_retrieval import AgentDeps

        seed = {"uri": "seed.md", "content": "previous turn"}
        deps = AgentDeps()
        deps.sources.append(seed)

        mock_result = MagicMock()
        attempts = []

        def run_sync(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                deps.sources.append({"uri": "stale.md", "content": "from failed attempt"})
                raise UnexpectedModelBehavior("transient")
            return mock_result

        agent = MagicMock()
        agent.run_sync = MagicMock(side_effect=run_sync)

        result = _run_with_retry(agent, "hello", deps, None, 15, time.monotonic())

        assert result is mock_result
        assert {"uri": "stale.md", "content": "from failed attempt"} not in deps.sources
        assert seed in deps.sources


class TestRunAgentBehavior(unittest.TestCase):
    @patch("backend_orchestrator.agents.agent.time.sleep")
    @patch("backend_orchestrator.agents.agent.normalize_citations")
    @patch("backend_orchestrator.agents.agent._process_cited_output")
    def test_transient_failure_returns_successful_result(self, mock_process, mock_normalize, mock_sleep):
        from backend_orchestrator.agents.agent import AgentOutput, AgentResponse, run_agent

        mock_result = MagicMock()
        mock_result.output = AgentResponse(answer="Test answer", cited_source_indices=[])
        mock_result.usage.return_value = MagicMock(
            requests=2, total_tokens=100, cache_read_tokens=0, cache_write_tokens=0
        )

        agent = MagicMock()
        agent.run_sync = MagicMock(
            side_effect=[
                ClientError({"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "InvokeModel"),
                mock_result,
            ]
        )

        mock_process.return_value = ("Test answer", [])
        mock_normalize.return_value = ([], "Test answer")

        output = run_agent(agent, "Wann kann ich in Rente gehen?")

        assert isinstance(output, AgentOutput)
        assert output.result == "Test answer"
        assert agent.run_sync.call_count == 2

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_double_transient_failure_raises(self, mock_sleep):
        from backend_orchestrator.agents.agent import run_agent

        agent = MagicMock()
        agent.run_sync = MagicMock(
            side_effect=[
                UnexpectedModelBehavior("first"),
                UnexpectedModelBehavior("second"),
            ]
        )

        with self.assertRaises(UnexpectedModelBehavior):
            run_agent(agent, "Test message")

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_non_retryable_client_error_is_logged_and_raised(self, mock_sleep):
        from backend_orchestrator.agents.agent import run_agent

        err = ClientError({"Error": {"Code": "ValidationException", "Message": "bad"}}, "InvokeModel")
        agent = MagicMock()
        agent.run_sync = MagicMock(side_effect=err)

        with self.assertRaises(ClientError):
            run_agent(agent, "Test message")


class TestSeedSourceSeparation(unittest.TestCase):
    """Seeded prior-turn sources must not leak into outputs unless the model actually cites them."""

    def test_process_cited_output_fallback_excludes_seeds(self):
        from backend_orchestrator.agents.agent import AgentResponse, _process_cited_output

        all_sources = [
            {"sourceIndex": 1, "title": "Seed"},
            {"sourceIndex": 2, "title": "Retrieved"},
        ]
        output = AgentResponse(answer="Antwort ohne Zitat", cited_source_indices=[])

        _text, sources = _process_cited_output(output, all_sources, {}, seed_count=1)

        assert [s["title"] for s in sources] == ["Retrieved"]

    def test_process_cited_output_keeps_cited_seed(self):
        from backend_orchestrator.agents.agent import AgentResponse, _process_cited_output

        all_sources = [
            {"sourceIndex": 1, "title": "Seed"},
            {"sourceIndex": 2, "title": "Retrieved"},
        ]
        output = AgentResponse(answer="Laut [1] gilt das.", cited_source_indices=[1])

        _text, sources = _process_cited_output(output, all_sources, {}, seed_count=1)

        assert [s["title"] for s in sources] == ["Seed"]

    def _run_agent_with(self, seed_sources, answer, cited):
        from backend_orchestrator.agents.agent import AgentResponse, run_agent
        from backend_orchestrator.tools.kb_retrieval import AgentDeps

        retrieved = {"sourceIndex": 2, "title": "New Brochure", "content": "new"}

        def run_sync(message, deps: AgentDeps, message_history=None, usage_limits=None):
            # Simulate the KB tool appending a freshly-retrieved source at K+1.
            deps.sources.append(retrieved)
            result = MagicMock()
            result.output = AgentResponse(answer=answer, cited_source_indices=cited)
            result.usage.return_value = MagicMock(
                requests=1, total_tokens=10, cache_read_tokens=0, cache_write_tokens=0
            )
            return result

        agent = MagicMock()
        agent.run_sync = MagicMock(side_effect=run_sync)
        return run_agent(agent, "Folgefrage", seed_sources=seed_sources)

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_run_agent_excludes_uncited_seed_from_related_documents(self, _sleep):
        """An un-cited seed stays out of all_sources (related_documents) and used sources."""
        seed = {"sourceIndex": 1, "title": "Seed Brochure", "content": "seed"}

        out = self._run_agent_with([seed], answer="Antwort ohne Zitat", cited=[])

        all_titles = [s["title"] for s in out.all_sources]
        used_titles = [s["title"] for s in out.sources]
        assert "Seed Brochure" not in all_titles
        assert "New Brochure" in all_titles
        assert "Seed Brochure" not in used_titles

    @patch("backend_orchestrator.agents.agent.time.sleep")
    def test_run_agent_keeps_cited_seed_in_outputs(self, _sleep):
        """A seed the model re-cites appears in both used sources and related_documents."""
        seed = {"sourceIndex": 1, "title": "Seed Brochure", "content": "seed"}

        out = self._run_agent_with([seed], answer="Laut [1] gilt das.", cited=[1])

        all_titles = [s["title"] for s in out.all_sources]
        used_titles = [s["title"] for s in out.sources]
        assert "Seed Brochure" in all_titles
        assert "Seed Brochure" in used_titles


if __name__ == "__main__":
    unittest.main()
