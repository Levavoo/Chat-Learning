"""Simplified pydantic-ai agent module."""

import re
import time
from datetime import UTC, datetime
from typing import Any, cast

from aws_lambda_powertools import Logger, Tracer
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage
from pydantic_ai.output import PromptedOutput
from pydantic_ai.usage import UsageLimits

from backend_orchestrator.config import get_config
from backend_orchestrator.glossary import build_glossary_prompt_context, load_glossary
from backend_orchestrator.prompts import SEARCH_AGENT_SYSTEM_PROMPT, SYSTEM_PROMPT
from backend_orchestrator.providers.bedrock_provider import (
    create_bedrock_model,
    get_bedrock_model_settings,
)
from backend_orchestrator.response_parser import unescape_literal_whitespace
from backend_orchestrator.tools.agent_search import fetch_section, list_sections, read_index
from backend_orchestrator.tools.kb_retrieval import AgentDeps
from backend_orchestrator.tools.pydantic_tools import get_pydantic_tools

logger = Logger(child=True)
tracer = Tracer()

_RETRYABLE_ERROR_CODES = frozenset({"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"})
_RETRY_DELAY_SECONDS = 1.0
_RETRY_TIME_BUDGET_SECONDS = 15.0


class AgentResponse(BaseModel):
    """Agent response containing the answer text and cited source indices."""

    answer: str
    cited_source_indices: list[int] = Field(
        default_factory=list,
        description="List of source indices [1, 2, 3] from the knowledge base that were used",
    )


CitedResponse = AgentResponse


class AgentOutput(BaseModel):
    """Validated agent output model."""

    result: str
    sources: list[dict[str, Any]]
    all_sources: list[dict[str, Any]]
    metadata: dict[str, Any] | None
    last_retrieval_query: str = ""


def _build_instructions(ctx: RunContext[AgentDeps]) -> str:
    """Build dynamic system prompt with current date and glossary context."""
    today = datetime.now(UTC).strftime("%d. %B %Y")
    base = f"{SYSTEM_PROMPT}\n\nHeutiges Datum: {today}"
    glossary = load_glossary()
    if glossary:
        base += f"\n\n{build_glossary_prompt_context(glossary)}"
    return base


def _brochure_key(source: dict[str, Any], fallback: str) -> str:
    return source.get("brochureNumber") or source.get("documentId") or source.get("sourceName") or fallback


def _group_sources_by_brochure(sources: list[dict[str, Any]]) -> dict[str, list[int]]:
    brochure_to_indices: dict[str, list[int]] = {}
    for i, source in enumerate(sources):
        key = _brochure_key(source, f"unknown-{i}")
        idx = source.get("sourceIndex")
        brochure_to_indices.setdefault(key, [])
        if idx is not None:
            brochure_to_indices[key].append(idx)
    return brochure_to_indices


def _build_normalized_sources(
    sources: list[dict[str, Any]], brochure_to_indices: dict[str, list[int]]
) -> tuple[list[dict[str, Any]], dict[int, int]]:
    index_mapping: dict[int, int] = {}
    normalized_sources: list[dict[str, Any]] = []
    brochure_normalized_index: dict[str, int] = {}

    for i, source in enumerate(sources):
        key = _brochure_key(source, f"unknown-{i}")
        idx = source.get("sourceIndex")

        if key in brochure_normalized_index:
            if idx is not None:
                index_mapping[idx] = brochure_normalized_index[key]
            existing = normalized_sources[brochure_normalized_index[key] - 1]
            new_content = source.get("content", "")
            if new_content and new_content != existing.get("content", ""):
                existing["content"] = existing.get("content", "") + "\n\n---\n\n" + new_content
            continue

        normalized_index = len(normalized_sources) + 1
        brochure_normalized_index[key] = normalized_index
        if idx is not None:
            index_mapping[idx] = normalized_index

        normalized_sources.append({**source, "sourceIndex": normalized_index})

    return normalized_sources, index_mapping


def normalize_citations(sources: list[dict[str, Any]], response_text: str) -> tuple[list[dict[str, Any]], str]:
    """Normalize citations by deduplicating brochures and renumbering."""
    if not sources:
        return sources, response_text

    brochure_to_indices = _group_sources_by_brochure(sources)
    normalized_sources, index_mapping = _build_normalized_sources(sources, brochure_to_indices)

    def replace_citation(match: re.Match) -> str:
        original_index = int(match.group(1))
        return f"[{index_mapping[original_index]}]" if original_index in index_mapping else match.group(0)

    normalized_text = re.sub(r"\[(\d+)\]", replace_citation, response_text)
    # Collapse adjacent duplicate markers, e.g. "[1], [1]" → "[1]"
    normalized_text = re.sub(r"(\[\d+\])([\s,;]*\1)+", r"\1", normalized_text)

    logger.info(
        "Normalized citations",
        extra={
            "original_source_count": len(sources),
            "normalized_source_count": len(normalized_sources),
            "index_mapping": {str(k): v for k, v in index_mapping.items()},
        },
    )

    return normalized_sources, normalized_text


def _process_cited_output(
    output: AgentResponse,
    all_sources: list[dict[str, Any]],
    log_extra: dict,
    label: str = "",
    seed_count: int = 0,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract response text and filter sources from agent output.

    ``all_sources`` is ``[seeds, retrieved]``. When the model cites nothing the fallback
    returns only the RETRIEVED sources — an un-cited seed is not "used" this turn.
    """
    # gpt-oss in JSON mode can double-escape newlines, leaving literal "\n" in the answer.
    response_text = unescape_literal_whitespace(output.answer)

    # Filter against real source indices so hallucinated or year-like numbers aren't treated as citations.
    available_indices = {s.get("sourceIndex") for s in all_sources if s.get("sourceIndex") is not None}
    cited_indices = {i for i in output.cited_source_indices if i in available_indices}
    invalid_structured_indices = set(output.cited_source_indices) - available_indices
    text_citations = {int(m) for m in re.findall(r"\[(\d+)\]", response_text) if int(m) in available_indices}
    invalid_text_indices = {int(m) for m in re.findall(r"\[(\d+)\]", response_text) if int(m) not in available_indices}

    valid_cited_indices = cited_indices | text_citations

    if invalid_text_indices:
        response_text = re.sub(
            r" ?\[(\d+)\]",
            lambda m: "" if int(m.group(1)) in invalid_text_indices else m.group(0),
            response_text,
        )
        log_extra["invalid_text_indices"] = list(invalid_text_indices)

    if valid_cited_indices:
        sources = [s for s in all_sources if s.get("sourceIndex") in valid_cited_indices]
    else:
        # No valid citations: return retrieved-only, never seeds.
        sources = all_sources[seed_count:]

    log_extra["cited_indices_from_structured"] = list(cited_indices)
    log_extra["invalid_structured_indices"] = list(invalid_structured_indices)
    log_extra["cited_indices_from_text"] = list(text_citations)
    log_extra["valid_cited_indices"] = list(valid_cited_indices)
    log_extra["available_indices"] = list(available_indices)
    log_extra["cited_sources_count"] = len(sources)
    log_extra["response_length"] = len(response_text) if response_text else 0
    logger.info(f"Agent completed with structured output{' ' + label if label else ''}", extra=log_extra)

    return response_text, sources


def _finalize_agent_output(
    output: AgentResponse,
    deps: AgentDeps,
    seed_count: int,
    log_extra: dict,
    metadata: dict[str, Any] | None,
    label: str = "",
) -> AgentOutput:
    """Build the AgentOutput, keeping un-cited seed sources out of the returned source lists."""
    run_sources = deps.sources
    retrieved_sources = run_sources[seed_count:]
    response_text, cited_sources = _process_cited_output(
        output, run_sources, log_extra, label=label, seed_count=seed_count
    )
    # Match against the cited list BEFORE normalize_citations creates new dicts.
    cited_ids = {id(s) for s in cited_sources}
    cited_seed_sources = [s for s in run_sources[:seed_count] if id(s) in cited_ids]
    all_sources = retrieved_sources + cited_seed_sources

    sources, response_text = normalize_citations(cited_sources, response_text)

    return AgentOutput(
        result=response_text,
        sources=sources,
        all_sources=all_sources,
        metadata=metadata,
        last_retrieval_query=deps.last_retrieval_query,
    )


def create_agent(rephrase: bool = True, model_id: str | None = None) -> Agent[AgentDeps, AgentResponse]:
    """Create pydantic-ai agent with Bedrock model.

    Uses PromptedOutput (plain JSON) instead of the default tool-based structured output,
    which gpt-oss-120b and similar Bedrock-hosted models ignore.
    """
    config = get_config()
    resolved_model_id = model_id or config.bedrock_model_id
    model = create_bedrock_model(resolved_model_id, region=config.aws_region)

    tools = get_pydantic_tools(rephrase=rephrase)
    settings = get_bedrock_model_settings()

    agent = cast(
        Agent[AgentDeps, AgentResponse],
        Agent(
            model=model,
            deps_type=AgentDeps,
            output_type=PromptedOutput(
                outputs=AgentResponse,
                template="\n ONLY respond with a valid JSON object exactly matching this schema:\n\n {schema}\n\n Don't add any extra text, schema repetition or Markdown fencing before or after.\n ",
            ),
            model_settings=settings,
            instructions=_build_instructions,
            tools=tools,
        ),
    )

    logger.info(
        "Created pydantic-ai agent",
        extra={
            "model_id": resolved_model_id,
            "region": config.aws_region,
            "tool_count": len(tools),
            "tool_names": [getattr(t, "__name__", str(t)) for t in tools],
            "settings": str(settings),
        },
    )
    return agent


_search_agent: Agent[None, str] | None = None


def create_search_agent() -> Agent[None, str]:
    """Create or return cached document search agent."""
    global _search_agent
    if _search_agent is not None:
        return _search_agent

    config = get_config()
    model = create_bedrock_model(config.agent_search_model_id, region=config.aws_region)
    settings = get_bedrock_model_settings(temperature=0.0, top_p=0.1)

    _search_agent = cast(
        Agent[None, str],
        Agent(  # ty: ignore[no-matching-overload]
            model=model,
            model_settings=settings,
            instructions=SEARCH_AGENT_SYSTEM_PROMPT,
            tools=[read_index, list_sections, fetch_section],
        ),
    )

    logger.info("Created search agent", extra={"model_id": config.agent_search_model_id})
    return _search_agent


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is retryable."""
    if isinstance(exc, UnexpectedModelBehavior):
        return True
    if isinstance(exc, ClientError):
        return exc.response["Error"]["Code"] in _RETRYABLE_ERROR_CODES
    return False


def _run_with_retry(
    agent: Agent[AgentDeps, AgentResponse],
    message: str,
    deps: AgentDeps,
    message_history: list[ModelMessage] | None,
    request_limit: int,
    start_time: float,
) -> Any:
    """Run agent.run_sync with a single retry for transient errors."""
    # Seeded history sources must survive a retry; only sources from the failed attempt are discarded.
    initial_sources = list(deps.sources)
    try:
        return agent.run_sync(
            message,
            deps=deps,
            message_history=message_history,
            usage_limits=UsageLimits(request_limit=request_limit),
        )
    except (UnexpectedModelBehavior, ClientError) as e:
        elapsed = time.monotonic() - start_time
        if not _is_retryable(e) or elapsed > _RETRY_TIME_BUDGET_SECONDS:
            raise

        logger.warning(
            "Transient error, retrying",
            extra={"retry_attempt": 1, "error_type": type(e).__name__, "error": str(e), "elapsed_seconds": elapsed},
        )
        time.sleep(_RETRY_DELAY_SECONDS)
        deps.sources[:] = initial_sources

        result = agent.run_sync(
            message,
            deps=deps,
            message_history=message_history,
            usage_limits=UsageLimits(request_limit=request_limit),
        )
        logger.info("Retry succeeded", extra={"retry_attempt": 1, "elapsed_seconds": time.monotonic() - start_time})
        return result


@tracer.capture_method(capture_response=False)
def run_agent(
    agent: Agent[AgentDeps, AgentResponse],
    message: str,
    message_history: list[ModelMessage] | None = None,
    request_limit: int = 15,
    seed_sources: list[dict[str, Any]] | None = None,
) -> AgentOutput:
    """Run agent and return standardized response.

    Args:
        agent: pydantic-ai Agent instance
        message: User input message
        message_history: Previous conversation messages for multi-turn context
        request_limit: Max model requests per run (prevents loops)
        seed_sources: Cited sources of the previous turn (indices 1..K); new KB results continue at K+1.

    Returns:
        AgentOutput with result, sources, all_sources, metadata and messages_json
    """
    seed_count = len(seed_sources) if seed_sources else 0
    deps = AgentDeps(original_question=message, sources=list(seed_sources) if seed_sources else [])

    logger.info(
        "Running agent",
        extra={
            "message_length": len(message),
            "history_len": len(message_history) if message_history else 0,
            "seed_source_count": seed_count,
        },
    )

    start_time = time.monotonic()

    try:
        result = _run_with_retry(agent, message, deps, message_history, request_limit, start_time)
    except UnexpectedModelBehavior as e:
        extra = {"error": str(e)}
        body = getattr(e, "body", None)
        if body is not None:
            extra["body"] = str(body)
        logger.exception("Unexpected model behavior", extra=extra)
        raise
    except ClientError as e:
        logger.exception(
            "AWS ClientError in agent run", extra={"error_code": e.response["Error"]["Code"], "error": str(e)}
        )
        raise

    usage = result.usage()
    log_extra: dict = {
        "request_count": usage.requests,
        "total_tokens": usage.total_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
    }

    metadata = {
        "requests": usage.requests,
        "total_tokens": usage.total_tokens,
    }

    return _finalize_agent_output(result.output, deps, seed_count, log_extra, metadata)


@tracer.capture_method(capture_response=False)
async def run_agent_async(
    agent: Agent[AgentDeps, AgentResponse],
    message: str,
    message_history: list[ModelMessage] | None = None,
    request_limit: int = 15,
    seed_sources: list[dict[str, Any]] | None = None,
) -> AgentOutput:
    """Run agent asynchronously and return standardized response.

    Mirrors run_agent minus the transient-error retry — async path used in local dev.
    TODO: Add async retry equivalent of _run_with_retry when this path goes to production.
    """
    seed_count = len(seed_sources) if seed_sources else 0
    deps = AgentDeps(original_question=message, sources=list(seed_sources) if seed_sources else [])

    logger.info(
        "Running agent (async)",
        extra={
            "message_length": len(message),
            "history_len": len(message_history) if message_history else 0,
            "seed_source_count": seed_count,
        },
    )

    result = await agent.run(
        message,
        deps=deps,
        message_history=message_history,
        usage_limits=UsageLimits(request_limit=request_limit),
    )

    usage = result.usage()
    log_extra: dict = {
        "request_count": usage.requests,
        "total_tokens": usage.total_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
    }

    metadata = {
        "requests": usage.requests,
        "total_tokens": usage.total_tokens,
    }

    return _finalize_agent_output(result.output, deps, seed_count, log_extra, metadata, label="(async)")
