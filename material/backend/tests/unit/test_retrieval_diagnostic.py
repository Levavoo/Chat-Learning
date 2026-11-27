from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend_orchestrator.retrieval_diagnostic import (
    is_retrieval_diagnostic_source,
    run_retrieval_diagnostic,
)


def _config(environment: str = "qa") -> SimpleNamespace:
    return SimpleNamespace(environment=environment)


def _snapshot() -> SimpleNamespace:
    return SimpleNamespace(
        retrieval_release_id="sha256-" + "a" * 64,
        retrieval_artifact_id="sha256-" + "b" * 64,
    )


@pytest.mark.parametrize(
    ("mode", "semantic_count", "bm25_count"),
    [("semantic", 1, 0), ("bm25", 0, 1), ("hybrid", 1, 1)],
)
def test_diagnostic_checks_one_release_in_every_mode(mode: str, semantic_count: int, bm25_count: int) -> None:
    snapshot = _snapshot()
    result = {"release_id": snapshot.retrieval_release_id}
    with (
        patch("backend_orchestrator.retrieval_diagnostic.get_config", return_value=_config()),
        patch(
            "backend_orchestrator.retrieval_diagnostic.snapshot_retrieval_config",
            return_value=snapshot,
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic._semantic_search",
            return_value=[result],
        ) as semantic,
        patch(
            "backend_orchestrator.retrieval_diagnostic.bm25_search",
            return_value=[result],
        ) as bm25,
    ):
        response = run_retrieval_diagnostic({"source": "qa-retrieval-promotion", "mode": mode, "query": "test"})

    assert response == {
        "ok": True,
        "mode": mode,
        "release_id": snapshot.retrieval_release_id,
        "retrieval_artifact_id": snapshot.retrieval_artifact_id,
        "semantic_results": semantic_count,
        "bm25_results": bm25_count,
        "observed_release_ids": [snapshot.retrieval_release_id],
    }
    assert semantic.call_count == semantic_count
    assert bm25.call_count == bm25_count


def test_diagnostic_fails_when_results_mix_releases() -> None:
    snapshot = _snapshot()
    with (
        patch("backend_orchestrator.retrieval_diagnostic.get_config", return_value=_config()),
        patch(
            "backend_orchestrator.retrieval_diagnostic.snapshot_retrieval_config",
            return_value=snapshot,
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic._semantic_search",
            return_value=[{"release_id": snapshot.retrieval_release_id}],
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic.bm25_search",
            return_value=[{"release_id": "sha256-" + "c" * 64}],
        ),
    ):
        response = run_retrieval_diagnostic({
            "source": "qa-retrieval-monitoring",
            "mode": "hybrid",
            "query": "test",
        })

    assert response["ok"] is False
    assert len(response["observed_release_ids"]) == 2


def test_diagnostic_is_limited_to_manifest_managed_environments() -> None:
    with (
        patch(
            "backend_orchestrator.retrieval_diagnostic.get_config",
            return_value=_config("dev"),
        ),
        pytest.raises(ValueError, match="limited to qa, preprod, and prod"),
    ):
        run_retrieval_diagnostic({"source": "qa-retrieval-promotion", "mode": "semantic", "query": "test"})


@pytest.mark.parametrize("environment", ["preprod", "prod"])
def test_downstream_diagnostic_uses_the_same_path(environment: str) -> None:
    snapshot = _snapshot()
    result = {"release_id": snapshot.retrieval_release_id}
    with (
        patch(
            "backend_orchestrator.retrieval_diagnostic.get_config",
            return_value=_config(environment),
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic.snapshot_retrieval_config",
            return_value=snapshot,
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic._semantic_search",
            return_value=[result],
        ),
        patch(
            "backend_orchestrator.retrieval_diagnostic.bm25_search",
            return_value=[],
        ),
    ):
        response = run_retrieval_diagnostic({
            "source": f"{environment}-retrieval-promotion",
            "mode": "semantic",
            "query": "test",
        })
    assert response["ok"] is True


@pytest.mark.parametrize("environment", ["qa", "preprod", "prod"])
@pytest.mark.parametrize("operation", ["promotion", "rollback", "monitoring"])
def test_manifest_managed_sources_are_routed(environment: str, operation: str) -> None:
    assert is_retrieval_diagnostic_source(f"{environment}-retrieval-{operation}")


def test_diagnostic_rejects_source_environment_mismatch() -> None:
    with (
        patch(
            "backend_orchestrator.retrieval_diagnostic.get_config",
            return_value=_config("preprod"),
        ),
        pytest.raises(ValueError, match="does not match"),
    ):
        run_retrieval_diagnostic({"source": "qa-retrieval-promotion", "mode": "semantic", "query": "test"})


@pytest.mark.parametrize(
    "event",
    [
        {"mode": "unknown", "query": "test"},
        {"mode": "semantic", "query": ""},
        {"mode": "semantic", "query": 123},
    ],
)
def test_diagnostic_rejects_invalid_requests(event: dict[str, object]) -> None:
    with (
        patch(
            "backend_orchestrator.retrieval_diagnostic.get_config",
            return_value=_config(),
        ),
        pytest.raises(ValueError),
    ):
        run_retrieval_diagnostic({"source": "qa-retrieval-promotion", **event})
