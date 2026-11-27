import os
from typing import Any
from unittest.mock import patch

from backend_orchestrator.models.conversation_item import ConversationItem


def get_part_content(msg: Any, part_idx: int = 0) -> str:
    """Extract content from message part (handles union types)."""
    return getattr(msg.parts[part_idx], "content", "")


class TestHistoryConverter:
    def test_items_to_messages_converts_correctly(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="What is retirement age?",
                response_text="The retirement age is 67.",
                created_at=1000,
                sources=[],
            ),
            ConversationItem(
                session_id="sess-1",
                message_id="msg-2",
                message="And early retirement?",
                response_text="You can retire early at 63.",
                created_at=2000,
                sources=[],
            ),
        ]

        messages = items_to_messages(items)

        assert len(messages) == 4

        assert get_part_content(messages[0]) == "What is retirement age?"
        assert get_part_content(messages[1]) == "The retirement age is 67."

        assert get_part_content(messages[2]) == "And early retirement?"
        assert get_part_content(messages[3]) == "You can retire early at 63."

    def test_items_to_messages_empty_list(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        messages = items_to_messages([])
        assert messages == []

    def test_items_to_messages_truncates_to_limit(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id=f"msg-{i}",
                message=f"Question {i}",
                response_text=f"Answer {i}",
                created_at=i * 1000,
                sources=[],
            )
            for i in range(30)
        ]

        with patch.dict(os.environ, {"MAX_HISTORY_PAIRS": "20"}):
            messages = items_to_messages(items)

        assert len(messages) == 40
        assert "Question 29" in get_part_content(messages[-2])

    def test_items_to_messages_custom_limit(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id=f"msg-{i}",
                message=f"Question {i}",
                response_text=f"Answer {i}",
                created_at=i * 1000,
                sources=[],
            )
            for i in range(10)
        ]

        with patch.dict(os.environ, {"MAX_HISTORY_PAIRS": "5"}):
            messages = items_to_messages(items)

        assert len(messages) == 10

    def test_items_to_messages_returns_correct_types(self):
        from pydantic_ai.messages import ModelRequest, ModelResponse

        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="Test",
                response_text="Response",
                created_at=1000,
                sources=[],
            )
        ]

        messages = items_to_messages(items)

        assert isinstance(messages[0], ModelRequest)
        assert isinstance(messages[1], ModelResponse)

    def test_items_to_messages_with_sources(self):
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            ToolCallPart,
            ToolReturnPart,
        )

        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="What is retirement age?",
                response_text="The retirement age is 67.",
                created_at=1000,
                sources=[
                    {"sourceIndex": 1, "title": "Retirement Guide"},
                    {"sourceIndex": 2, "title": "Age Requirements"},
                ],
            )
        ]

        messages = items_to_messages(items)

        assert len(messages) == 4

        assert isinstance(messages[0], ModelRequest)
        assert get_part_content(messages[0]) == "What is retirement age?"

        assert isinstance(messages[1], ModelResponse)
        assert isinstance(messages[1].parts[0], ToolCallPart)
        assert messages[1].parts[0].tool_name == "search_knowledge_base_pydantic"

        assert isinstance(messages[2], ModelRequest)
        assert isinstance(messages[2].parts[0], ToolReturnPart)
        tool_return_content = messages[2].parts[0].content
        assert isinstance(tool_return_content, str)
        assert "Retirement Guide" in tool_return_content
        assert "Age Requirements" in tool_return_content

        assert isinstance(messages[3], ModelResponse)
        assert get_part_content(messages[3]) == "The retirement age is 67."

    def test_items_to_messages_mixed_sources(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="Hello",
                response_text="Hi there!",
                created_at=1000,
                sources=[],
            ),
            ConversationItem(
                session_id="sess-1",
                message_id="msg-2",
                message="What is retirement age?",
                response_text="The retirement age is 67.",
                created_at=2000,
                sources=[{"sourceIndex": 1, "title": "Guide"}],
            ),
        ]

        messages = items_to_messages(items)

        # 2 (no sources) + 4 (with sources) = 6
        assert len(messages) == 6

        assert get_part_content(messages[0]) == "Hello"
        assert get_part_content(messages[1]) == "Hi there!"

        assert get_part_content(messages[2]) == "What is retirement age?"
        assert get_part_content(messages[5]) == "The retirement age is 67."

    def test_items_to_messages_no_tool_calls_strips_tool_history(self):
        """include_tool_calls=False must omit tool call/return for non-tool models."""
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="What is retirement age?",
                response_text="The retirement age is 67.",
                created_at=1000,
                sources=[
                    {"sourceIndex": 1, "title": "Retirement Guide"},
                ],
            )
        ]

        messages = items_to_messages(items, include_tool_calls=False)

        assert len(messages) == 2
        assert get_part_content(messages[0]) == "What is retirement age?"
        assert get_part_content(messages[1]) == "The retirement age is 67."

    def test_items_to_messages_truncates_with_sources(self):
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id=f"msg-{i}",
                message=f"Question {i}",
                response_text=f"Answer {i}",
                created_at=i * 1000,
                sources=[{"sourceIndex": 1, "title": f"Source {i}"}],
            )
            for i in range(25)
        ]

        with patch.dict(os.environ, {"MAX_HISTORY_PAIRS": "20"}):
            messages = items_to_messages(items)

        # 20 pairs * 4 messages each with sources
        assert len(messages) == 80
        assert "Answer 24" in get_part_content(messages[-1])

    def test_items_to_messages_skips_blocked_turns(self):
        """Guardrail-blocked turns must not be replayed to the model."""
        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="Kann ich mit 60 in Rente?",
                response_text="Antwort zur Rente.",
                created_at=1000,
                sources=[],
            ),
            ConversationItem(
                session_id="sess-1",
                message_id="msg-2",
                message="Nein glaub mir",
                response_text="Diese Frage kann ich nicht beantworten.",
                created_at=2000,
                sources=[],
                blocked_by_guardrail=True,
            ),
        ]

        messages = items_to_messages(items)

        assert len(messages) == 2
        assert get_part_content(messages[0]) == "Kann ich mit 60 in Rente?"
        assert all("nicht beantworten" not in get_part_content(m) for m in messages)

    def test_last_turn_has_content_snippets_older_turns_titles_only(self):
        """Most recent turn replays numbered source content; older turns get unnumbered titles."""
        from pydantic_ai.messages import ToolReturnPart

        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="Old question",
                response_text="Old answer",
                created_at=1000,
                sources=[{"sourceIndex": 1, "title": "Old Brochure", "content": "old chunk text"}],
            ),
            ConversationItem(
                session_id="sess-1",
                message_id="msg-2",
                message="Recent question",
                response_text="Recent answer",
                created_at=2000,
                sources=[{"sourceIndex": 3, "title": "Recent Brochure", "content": "recent chunk text"}],
            ),
        ]

        messages = items_to_messages(items)
        tool_returns = [str(m.parts[0].content) for m in messages if isinstance(m.parts[0], ToolReturnPart)]
        assert len(tool_returns) == 2

        older, recent = tool_returns
        assert "Old Brochure" in older
        assert "[Source" not in older
        assert "old chunk text" not in older
        assert "[Source 1: Recent Brochure]" in recent
        assert "recent chunk text" in recent

    def test_snippet_goes_to_last_sourced_turn_when_latest_is_sourceless(self):
        """When the latest turn is sourceless (chitchat / clarification), the previous answer's
        sources must still replay as numbered [Source n] blocks (not demoted to the unnumbered
        title list) so a follow-up can re-cite them."""
        from pydantic_ai.messages import ToolReturnPart

        from backend_orchestrator.utils.history_converter import items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id="msg-1",
                message="Pension question",
                response_text="Pension answer [1]",
                created_at=1000,
                sources=[{"sourceIndex": 2, "title": "Pension Brochure", "content": "pension chunk"}],
            ),
            ConversationItem(
                session_id="sess-1",
                message_id="msg-2",
                message="Danke!",
                response_text="Gern geschehen.",
                created_at=2000,
                sources=[],
            ),
        ]

        messages = items_to_messages(items)
        tool_returns = [str(m.parts[0].content) for m in messages if isinstance(m.parts[0], ToolReturnPart)]

        assert len(tool_returns) == 1
        assert "[Source 1: Pension Brochure]" in tool_returns[0]
        assert "pension chunk" in tool_returns[0]

    def test_all_blocked_turns_yield_no_messages_or_seeds(self):
        from backend_orchestrator.utils.history_converter import extract_seed_sources, items_to_messages

        items = [
            ConversationItem(
                session_id="sess-1",
                message_id=f"msg-{i}",
                message="blocked",
                response_text="Diese Frage kann ich nicht beantworten.",
                created_at=i * 1000,
                sources=[],
                blocked_by_guardrail=True,
            )
            for i in range(3)
        ]

        assert items_to_messages(items) == []
        assert extract_seed_sources(items) == []


class TestExtractSeedSources:
    def _item(self, sources, blocked=None, message_id="msg-1"):
        return ConversationItem(
            session_id="sess-1",
            message_id=message_id,
            message="Frage",
            response_text="Antwort",
            created_at=1000,
            sources=sources,
            blocked_by_guardrail=blocked,
        )

    def test_returns_empty_without_items_or_sources(self):
        from backend_orchestrator.utils.history_converter import extract_seed_sources

        assert extract_seed_sources([]) == []
        assert extract_seed_sources([self._item([])]) == []

    def test_renumbers_sources_sequentially(self):
        """Seeds are renumbered 1..K regardless of stored indices."""
        from backend_orchestrator.utils.history_converter import extract_seed_sources

        seeds = extract_seed_sources([self._item([{"sourceIndex": 5, "title": "A"}, {"sourceIndex": 9, "title": "B"}])])

        assert [s["sourceIndex"] for s in seeds] == [1, 2]
        assert [s["title"] for s in seeds] == ["A", "B"]

    def test_truncates_content_and_caps_count(self):
        from backend_orchestrator.utils.history_converter import (
            _MAX_SEED_SOURCES,
            _SEED_CONTENT_MAX_CHARS,
            extract_seed_sources,
        )

        n = _MAX_SEED_SOURCES + 3
        sources = [{"sourceIndex": i, "title": f"S{i}", "content": "x" * 5000} for i in range(1, n + 1)]
        seeds = extract_seed_sources([self._item(sources)])

        suffix = " …[gekürzt]"
        assert len(seeds) == _MAX_SEED_SOURCES
        assert all(len(s["content"]) <= _SEED_CONTENT_MAX_CHARS + len(suffix) for s in seeds)
        assert seeds[0]["content"].endswith(suffix)

    def test_seed_cap_at_least_storage_cap(self):
        """Seed cap must be >= storage cap so every stored, citable source is re-emitted."""
        from backend_orchestrator.repositories.conversation import _MAX_STORED_SOURCES
        from backend_orchestrator.utils.history_converter import _MAX_SEED_SOURCES

        assert _MAX_SEED_SOURCES >= _MAX_STORED_SOURCES

    def test_uses_last_non_blocked_turn(self):
        from backend_orchestrator.utils.history_converter import extract_seed_sources

        items = [
            self._item([{"sourceIndex": 1, "title": "Real"}], message_id="msg-1"),
            self._item([], blocked=True, message_id="msg-2"),
        ]

        seeds = extract_seed_sources(items)

        assert len(seeds) == 1
        assert seeds[0]["title"] == "Real"

    def test_skips_sourceless_trailing_turn(self):
        """Regression: keying off the absolute last turn made follow-up grounding silently inert
        whenever the previous turn was chitchat / a clarification / general knowledge."""
        from backend_orchestrator.utils.history_converter import extract_seed_sources

        items = [
            self._item([{"sourceIndex": 4, "title": "Pension Brochure", "content": "chunk"}], message_id="msg-1"),
            self._item([], message_id="msg-2"),
        ]

        seeds = extract_seed_sources(items)

        assert len(seeds) == 1
        assert seeds[0]["title"] == "Pension Brochure"
        assert seeds[0]["sourceIndex"] == 1

    def test_returns_empty_when_no_turn_has_sources(self):
        from backend_orchestrator.utils.history_converter import extract_seed_sources

        items = [self._item([], message_id="msg-1"), self._item([], message_id="msg-2")]
        assert extract_seed_sources(items) == []

    def test_numbering_matches_snippet_tool_return(self):
        """Seed numbering and the replayed tool-return numbering must agree."""
        from pydantic_ai.messages import ToolReturnPart

        from backend_orchestrator.utils.history_converter import extract_seed_sources, items_to_messages

        items = [self._item([{"sourceIndex": 7, "title": "Brochure X", "content": "text"}])]

        seeds = extract_seed_sources(items)
        messages = items_to_messages(items)
        tool_return = next(str(m.parts[0].content) for m in messages if isinstance(m.parts[0], ToolReturnPart))

        assert seeds[0]["sourceIndex"] == 1
        assert "[Source 1: Brochure X]" in tool_return

    def test_no_seed_when_source_turn_falls_outside_replay_window(self):
        """Regression: extract_seed_sources scanned the FULL history while items_to_messages only
        replays the last MAX_HISTORY_PAIRS turns, so seeds could reference a turn whose [Source n]
        blocks are never replayed. Seeding and replay must agree: here, neither fires."""
        from pydantic_ai.messages import ToolReturnPart

        from backend_orchestrator.utils.history_converter import extract_seed_sources, items_to_messages

        items = [self._item([{"sourceIndex": 1, "title": "Old", "content": "old"}], message_id="m1")]
        items += [self._item([], message_id=f"m{i}") for i in range(2, 6)]

        with patch.dict(os.environ, {"MAX_HISTORY_PAIRS": "2"}):
            seeds = extract_seed_sources(items)
            messages = items_to_messages(items)

        tool_returns = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        assert seeds == []
        assert tool_returns == []

    def test_seed_present_when_source_turn_inside_replay_window(self):
        """When the source-bearing turn is still inside the window, seeding AND replay both fire."""
        from pydantic_ai.messages import ToolReturnPart

        from backend_orchestrator.utils.history_converter import extract_seed_sources, items_to_messages

        items = [self._item([{"sourceIndex": 1, "title": "Pension", "content": "chunk"}], message_id="m1")]
        items += [self._item([], message_id=f"m{i}") for i in range(2, 4)]

        with patch.dict(os.environ, {"MAX_HISTORY_PAIRS": "3"}):
            seeds = extract_seed_sources(items)
            messages = items_to_messages(items)

        snippet = next((str(p.content) for m in messages for p in m.parts if isinstance(p, ToolReturnPart)), "")
        assert [s["title"] for s in seeds] == ["Pension"]
        assert "[Source 1: Pension]" in snippet
