"""Regression tests for DSFA log redaction (#664 AC3): no free-text content in agent logs."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.agents.agent import AgentResponse, run_agent, run_agent_async


def _mock_result(answer: str, cited: list[int] | None = None):
    result = MagicMock()
    result.output = AgentResponse(answer=answer, cited_source_indices=cited or [])
    result.usage.return_value = MagicMock(requests=1, total_tokens=10, cache_read_tokens=0, cache_write_tokens=0)
    return result


class TestRunAgentLogRedaction(unittest.TestCase):
    """logger.info extra= payloads must never carry raw message/response content."""

    @patch("backend_orchestrator.agents.agent.time.sleep")
    @patch("backend_orchestrator.agents.agent.logger")
    def test_run_agent_logs_length_not_preview(self, mock_logger, _sleep):
        sensitive_message = "Meine SVNR ist 12 345678 A 123, wie hoch ist meine Rente?"
        agent = MagicMock()
        agent.run_sync = MagicMock(return_value=_mock_result("Die Antwort lautet: 1200 EUR."))

        run_agent(agent, sensitive_message)

        logged_content = []
        for call in mock_logger.info.call_args_list:
            _args, kwargs = call
            extra = kwargs.get("extra", {})
            assert "message_preview" not in extra
            assert "response_preview" not in extra
            logged_content.extend(str(v) for v in extra.values())

        combined = " ".join(logged_content)
        assert sensitive_message not in combined
        assert "12 345678 A 123" not in combined

        run_extra = mock_logger.info.call_args_list[0].kwargs["extra"]
        assert run_extra["message_length"] == len(sensitive_message)


@patch("backend_orchestrator.agents.agent.logger")
@pytest.mark.asyncio
async def test_run_agent_async_logs_length_not_preview(mock_logger):
    sensitive_message = "Meine Adresse ist Musterstraße 1, 12345 Berlin, Diagnose: Depression"
    agent = MagicMock()

    async def run(*_args, **_kwargs):
        return _mock_result("Antwort ohne Bezug zu Details.")

    agent.run = run

    await run_agent_async(agent, sensitive_message)

    logged_content = []
    for call in mock_logger.info.call_args_list:
        _args, kwargs = call
        extra = kwargs.get("extra", {})
        assert "message_preview" not in extra
        assert "response_preview" not in extra
        logged_content.extend(str(v) for v in extra.values())

    combined = " ".join(logged_content)
    assert sensitive_message not in combined
    assert "Musterstraße" not in combined
    assert "Depression" not in combined

    run_extra = mock_logger.info.call_args_list[0].kwargs["extra"]
    assert run_extra["message_length"] == len(sensitive_message)


if __name__ == "__main__":
    unittest.main()
