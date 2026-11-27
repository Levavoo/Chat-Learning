"""Resolve one atomic retrieval manifest per request with a bounded cache."""

import copy
import logging
import time
from dataclasses import dataclass
from typing import Any

import boto3

from bm25_shared.retrieval_manifest import RetrievalManifest
from bm25_shared.tokenizer import TOKENIZER_REVISION

logger = logging.getLogger(__name__)

MANIFEST_CACHE_TTL_SECONDS = 60
LEGACY_RELEASE_ID = "legacy-environment"


class RetrievalManifestUnavailableError(RuntimeError):
    """Raised when a configured selector has no validated manifest."""


@dataclass(frozen=True, slots=True)
class RetrievalSnapshot:
    """Coordinates used by every retrieval path during one request."""

    release_id: str
    retrieval_artifact_id: str
    knowledge_base_id: str
    data_source_id: str
    bm25_bucket: str
    bm25_key: str
    bm25_tokenizer_revision: str
    version: str
    data_artifact_version: str
    etl_version: str
    legacy_fallback: bool = False

    @classmethod
    def from_manifest(cls, manifest: RetrievalManifest) -> "RetrievalSnapshot":
        """Create a runtime snapshot from a validated selector value."""
        return cls(
            release_id=manifest.release_id,
            retrieval_artifact_id=manifest.artifact_id,
            knowledge_base_id=manifest.knowledge_base_id,
            data_source_id=manifest.data_source_id,
            bm25_bucket=manifest.bm25_bucket,
            bm25_key=manifest.bm25_key,
            bm25_tokenizer_revision=manifest.bm25_tokenizer_revision,
            version=manifest.version,
            data_artifact_version=manifest.data_artifact_version,
            etl_version=manifest.etl_version,
        )

    @classmethod
    def from_legacy_environment(cls, config: Any) -> "RetrievalSnapshot":
        """Snapshot the migration-only deployment environment coordinates."""
        return cls(
            release_id=LEGACY_RELEASE_ID,
            retrieval_artifact_id=LEGACY_RELEASE_ID,
            knowledge_base_id=config.knowledge_base_id,
            data_source_id="",
            bm25_bucket=config.bm25_index_bucket,
            bm25_key=config.bm25_index_key,
            bm25_tokenizer_revision=TOKENIZER_REVISION,
            version="legacy",
            data_artifact_version="legacy",
            etl_version="legacy",
            legacy_fallback=True,
        )


@dataclass(slots=True)
class _CacheEntry:
    snapshot: RetrievalSnapshot
    expires_at: float


_cache: dict[str, _CacheEntry] = {}
_last_good: dict[str, RetrievalSnapshot] = {}
_ssm_clients: dict[str, Any] = {}


def _get_ssm_client(region: str):
    client = _ssm_clients.get(region)
    if client is None:
        client = boto3.client("ssm", region_name=region)
        _ssm_clients[region] = client
    return client


def _validate_runtime_compatibility(manifest: RetrievalManifest) -> None:
    if manifest.bm25_tokenizer_revision != TOKENIZER_REVISION:
        raise ValueError(
            "active BM25 tokenizer revision "
            f"{manifest.bm25_tokenizer_revision!r} is incompatible with runtime revision {TOKENIZER_REVISION!r}"
        )


def resolve_retrieval_snapshot(config: Any) -> RetrievalSnapshot:
    """Resolve and validate one complete SSM manifest.

    A successful manifest is cached for 60 seconds. On a transient refresh
    failure, the last validated manifest remains coherent and is used for
    another bounded retry interval. Deployments without a configured selector
    use the legacy environment snapshot; once a selector is configured, an
    initial missing or invalid value fails closed rather than silently
    selecting unrelated mutable environment coordinates.
    """
    parameter_name = getattr(config, "retrieval_manifest_parameter", "")
    if not isinstance(parameter_name, str) or not parameter_name:
        return RetrievalSnapshot.from_legacy_environment(config)

    now = time.monotonic()
    cached = _cache.get(parameter_name)
    if cached is not None and now < cached.expires_at:
        return cached.snapshot

    try:
        response = _get_ssm_client(config.aws_region).get_parameter(Name=parameter_name)
        value = response["Parameter"]["Value"]
        manifest = RetrievalManifest.from_json(value)
        _validate_runtime_compatibility(manifest)
        snapshot = RetrievalSnapshot.from_manifest(manifest)
        _last_good[parameter_name] = snapshot
        logger.info("Resolved active retrieval manifest", extra={"release_id": snapshot.release_id})
    except Exception as exc:
        snapshot = _last_good.get(parameter_name)
        if snapshot is None:
            logger.error(
                "Configured retrieval manifest unavailable; failing closed",
                extra={"parameter_name": parameter_name},
                exc_info=True,
            )
            raise RetrievalManifestUnavailableError(
                f"configured retrieval manifest {parameter_name!r} is unavailable"
            ) from exc
        else:
            logger.warning(
                "Active retrieval manifest refresh failed; retaining last validated release",
                extra={"parameter_name": parameter_name, "release_id": snapshot.release_id},
                exc_info=True,
            )

    _cache[parameter_name] = _CacheEntry(
        snapshot=snapshot,
        expires_at=now + MANIFEST_CACHE_TTL_SECONDS,
    )
    return snapshot


def snapshot_retrieval_config(config: Any) -> Any:
    """Copy app config and bind both semantic and BM25 paths to one snapshot."""
    snapshot = resolve_retrieval_snapshot(config)
    request_config = copy.copy(config)
    request_config.knowledge_base_id = snapshot.knowledge_base_id
    request_config.bm25_index_bucket = snapshot.bm25_bucket
    request_config.bm25_index_key = snapshot.bm25_key
    request_config.bm25_tokenizer_revision = snapshot.bm25_tokenizer_revision
    request_config.retrieval_release_id = snapshot.release_id
    request_config.retrieval_artifact_id = snapshot.retrieval_artifact_id
    request_config.retrieval_legacy_fallback = snapshot.legacy_fallback
    return request_config


def reset_retrieval_manifest_cache() -> None:
    """Clear resolver state for tests and controlled runtime diagnostics."""
    _cache.clear()
    _last_good.clear()
    _ssm_clients.clear()
