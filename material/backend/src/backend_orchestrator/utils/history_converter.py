"""Convert conversation items to pydantic-ai message format."""

import os
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from backend_orchestrator.models.conversation_item import ConversationItem

DEFAULT_MAX_HISTORY_PAIRS = 20

_HISTORY_TOOL_CALL_ID = "history-kb-"

# Keep _MAX_SEED_SOURCES >= the storage cap (_MAX_STORED_SOURCES in
# repositories/conversation.py) so every stored, citable source of the replayed
# turn is re-emitted; otherwise the replayed answer carries dangling [n] markers
# with no matching [Source n] block.
_MAX_SEED_SOURCES = 8
_SEED_CONTENT_MAX_CHARS = 1500


def drop_blocked_turns(items: list[ConversationItem]) -> list[ConversationItem]:
    """Drop guardrail-blocked turns from a conversation history.

    A blocked turn is a canned refusal, not real dialogue: replaying it primes
    the model to repeat refusals and biases the follow-up classifier. Both
    consumers share this helper so their notion of "real" turns cannot drift.
    """
    return [item for item in items if not item.blocked_by_guardrail]


def _max_history_pairs() -> int:
    return int(os.getenv("MAX_HISTORY_PAIRS", str(DEFAULT_MAX_HISTORY_PAIRS)))


def _replayed_turns(items: list[ConversationItem]) -> list[ConversationItem]:
    """Return the non-blocked turns actually replayed to the model.

    Seed selection and history reconstruction MUST share this exact window.
    Seeding a turn whose [Source n] blocks fall outside the replay window
    would hand the model citable indices with no visible content.
    """
    return drop_blocked_turns(items)[-_max_history_pairs() :]


def _seed_turn(items: list[ConversationItem]) -> ConversationItem | None:
    """Return the most recent source-bearing turn WITHIN the replay window.

    A trailing sourceless turn (chitchat, clarification) must not hide the last
    real answer; a source-bearing turn that has scrolled out of the replay
    window must not be seeded, or the model gets citable indices with no
    visible content.
    """
    for item in reversed(_replayed_turns(items)):
        if item.sources:
            return item
    return None


def _source_title(source: dict[str, Any]) -> str:
    return source.get("title") or source.get("sourceName") or "Unbekannte Quelle"


def extract_seed_sources(items: list[ConversationItem]) -> list[dict[str, Any]]:
    """Return the most recent source-bearing turn's sources, renumbered 1..K.

    Seeded into AgentDeps.sources before the agent runs: the reconstructed tool
    return for that same turn (see _snippet_tool_return) shows the same
    [Source 1..K] numbering so the model can re-cite them and the citation
    filter resolves the indices. New KB results continue at K+1.
    """
    source_item = _seed_turn(items)
    if source_item is None:
        return []

    seeds: list[dict[str, Any]] = []
    for i, source in enumerate(source_item.sources[:_MAX_SEED_SOURCES], 1):
        seed = dict(source)
        content = seed.get("content")
        if isinstance(content, str) and len(content) > _SEED_CONTENT_MAX_CHARS:
            seed["content"] = content[:_SEED_CONTENT_MAX_CHARS] + " …[gekürzt]"
        seed["sourceIndex"] = i
        seeds.append(seed)
    return seeds


def _snippet_tool_return(item: ConversationItem) -> str:
    """Tool return for the most recent turn: numbered source blocks with content.

    Mirrors the live KB tool format and the numbering of extract_seed_sources.
    Older turns use _titles_tool_return instead; numbered entries there would
    collide with the current turn's [1..N] numbering.
    """
    seeds = extract_seed_sources([item])
    blocks = [f"[Source {seed['sourceIndex']}: {_source_title(seed)}]\n{seed.get('content') or ''}\n" for seed in seeds]
    return (
        f"Found {len(seeds)} relevant document(s):\n\n"
        + "\n".join(blocks)
        + "\n[Hinweis: Suchergebnisse der vorherigen Frage, weiterhin mit [n] zitierbar."
        " Für neue Aspekte oder Personengruppen führe eine neue Suche aus.]"
    )


def _titles_tool_return(item: ConversationItem) -> str:
    """Tool return for older turns: compact, deliberately unnumbered title list."""
    titles = sorted({_source_title(source) for source in item.sources})
    return (
        "Verwendete Quellen dieser früheren Suche (Inhalte nicht mehr geladen,"
        " nicht mit [n] zitierbar — für neue Aspekte erneut suchen):\n" + "\n".join(f"- {title}" for title in titles)
    )


def items_to_messages(
    items: list[ConversationItem],
    *,
    include_tool_calls: bool = True,
) -> list[ModelMessage]:
    """Convert ConversationItems to pydantic-ai ModelMessage list.

    Reconstructs tool call/return pairs so the model sees that previous turns
    used tools. The most recent source-bearing turn replays its cited sources
    with content snippets (numbered to match extract_seed_sources); every other
    source-bearing turn carries only an unnumbered title list. Guardrail-blocked
    turns are skipped.

    Args:
        items: List of ConversationItem from DynamoDB
        include_tool_calls: If False, omit tool call/return reconstruction.
            Set to False for models that don't support tools (e.g. Mistral).

    """
    truncated = _replayed_turns(items)
    if not truncated:
        return []

    seed_item = _seed_turn(items)

    messages: list[ModelMessage] = []

    for idx, item in enumerate(truncated):
        messages.append(ModelRequest(parts=[UserPromptPart(content=item.message)]))

        if item.sources and include_tool_calls:
            tool_call_id = f"{_HISTORY_TOOL_CALL_ID}{idx}"
            content = _snippet_tool_return(item) if item is seed_item else _titles_tool_return(item)
            messages.append(
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="search_knowledge_base_pydantic",
                            args={"query": item.message},
                            tool_call_id=tool_call_id,
                        ),
                    ]
                )
            )
            messages.append(
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name="search_knowledge_base_pydantic",
                            content=content,
                            tool_call_id=tool_call_id,
                        ),
                    ]
                )
            )
        messages.append(ModelResponse(parts=[TextPart(content=item.response_text)]))

    return messages
