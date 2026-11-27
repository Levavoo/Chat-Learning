"""Direct Lambda diagnostics for manifest-managed retrieval environments."""

from typing import Any

from backend_orchestrator.config import get_config
from backend_orchestrator.retrieval_manifest import snapshot_retrieval_config
from backend_orchestrator.tools.bm25_search import bm25_search
from backend_orchestrator.tools.kb_retrieval import _semantic_search

_ALLOWED_MODES = frozenset({"semantic", "bm25", "hybrid"})
_DIAGNOSTIC_SOURCES = {
    environment: frozenset({
        f"{environment}-retrieval-promotion",
        f"{environment}-retrieval-rollback",
        f"{environment}-retrieval-monitoring",
    })
    for environment in ("qa", "preprod", "prod")
}
_ALL_DIAGNOSTIC_SOURCES = frozenset().union(*_DIAGNOSTIC_SOURCES.values())


def is_retrieval_diagnostic_source(source: Any) -> bool:
    """Return whether an event source is one of the explicit diagnostic routes."""
    return isinstance(source, str) and source in _ALL_DIAGNOSTIC_SOURCES


def run_retrieval_diagnostic(event: dict[str, Any]) -> dict[str, Any]:
    """Run one retrieval path against one request-scoped manifest snapshot."""
    config = get_config()
    environment = getattr(config, "environment", "")
    if environment not in _DIAGNOSTIC_SOURCES:
        raise ValueError("retrieval promotion diagnostics are limited to qa, preprod, and prod")
    if event.get("source") not in _DIAGNOSTIC_SOURCES[environment]:
        raise ValueError("diagnostic source does not match the runtime environment")

    mode = event.get("mode")
    query = event.get("query")
    if mode not in _ALLOWED_MODES:
        raise ValueError("diagnostic mode must be semantic, bm25, or hybrid")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("diagnostic query must be a non-empty string")

    request_config = snapshot_retrieval_config(config)
    semantic = []
    lexical = []
    if mode in {"semantic", "hybrid"}:
        semantic = _semantic_search(query, request_config)
    if mode in {"bm25", "hybrid"}:
        lexical = bm25_search(query, top_k=10, retrieval_snapshot=request_config)

    selected = [*semantic, *lexical]
    release_ids = sorted({item.get("release_id") for item in selected if item.get("release_id")})
    expected_release = request_config.retrieval_release_id
    coherent = bool(selected) and release_ids == [expected_release]
    return {
        "ok": coherent,
        "mode": mode,
        "release_id": expected_release,
        "retrieval_artifact_id": request_config.retrieval_artifact_id,
        "semantic_results": len(semantic),
        "bm25_results": len(lexical),
        "observed_release_ids": release_ids,
    }
