"""BM25 keyword search with lazy index loading from S3."""

import json
import time

import boto3
import numpy as np
from aws_lambda_powertools import Logger
from rank_bm25 import BM25Okapi

from backend_orchestrator.config import get_config
from backend_orchestrator.retrieval_manifest import LEGACY_RELEASE_ID
from bm25_shared.tokenizer import TOKENIZER_REVISION, tokenize

logger = Logger(child=True)

_bm25_index: dict | None = None
_bm25_loaded_at: float = 0
_bm25_load_failed_until: float = 0
_bm25_cache_artifact_id: str | None = None
_bm25_failed_artifact_id: str | None = None
_BM25_RETRY_INTERVAL = 60
# Legacy mutable index only; release indexes are immutable.
_BM25_TTL = 300


def _release_id(config) -> str:
    release_id = getattr(config, "retrieval_release_id", LEGACY_RELEASE_ID)
    return release_id if isinstance(release_id, str) and release_id else LEGACY_RELEASE_ID


def _artifact_id(config, release_id: str) -> str:
    artifact_id = getattr(config, "retrieval_artifact_id", release_id)
    return artifact_id if isinstance(artifact_id, str) and artifact_id else release_id


def _validate_release_index(raw: dict, config, release_id: str, artifact_id: str, legacy_index: bool) -> None:
    schema_version = raw.get("schema_version", 1)
    if not legacy_index and schema_version == 1 and raw.get("release_id") != release_id:
        raise ValueError(f"BM25 release mismatch: selector={release_id!r}, index={raw.get('release_id')!r}")
    if not legacy_index and schema_version == 2 and raw.get("retrieval_artifact_id") != artifact_id:
        raise ValueError(
            f"BM25 artifact mismatch: selector={artifact_id!r}, index={raw.get('retrieval_artifact_id')!r}"
        )
    if not legacy_index and schema_version not in (1, 2):
        raise ValueError(f"unsupported BM25 index schema_version: {schema_version!r}")
    expected_revision = getattr(config, "bm25_tokenizer_revision", TOKENIZER_REVISION)
    if not legacy_index and raw.get("bm25_tokenizer_revision") != expected_revision:
        raise ValueError(
            f"BM25 tokenizer mismatch: selector={expected_revision!r}, index={raw.get('bm25_tokenizer_revision')!r}"
        )


def _reconstruct_index(raw: dict, artifact_id: str) -> dict:
    chunk_ids = raw["chunk_ids"]
    chunk_contents = raw["chunk_contents"]
    chunk_metadata = raw.get("chunk_metadata", [{} for _ in chunk_ids])
    if not (len(chunk_ids) == len(chunk_contents) == len(chunk_metadata) == len(raw["corpus"])):
        raise ValueError("BM25 index arrays must have identical lengths")
    return {
        "bm25": BM25Okapi(raw["corpus"]),
        "chunk_ids": chunk_ids,
        "chunk_contents": chunk_contents,
        "chunk_metadata": chunk_metadata,
        # Chunk-key lookup so semantic-only hits can recover release-pinned metadata without an S3 GetObject.
        "metadata_by_key": dict(zip(chunk_ids, chunk_metadata, strict=True)),
        "retrieval_artifact_id": artifact_id,
    }


def _load_index(retrieval_snapshot=None) -> dict | None:
    """Download BM25 index JSON from S3, reconstruct BM25Okapi. Returns None on failure."""
    global _bm25_index, _bm25_loaded_at, _bm25_load_failed_until
    global _bm25_cache_artifact_id, _bm25_failed_artifact_id

    config = retrieval_snapshot or get_config()
    release_id = _release_id(config)
    artifact_id = _artifact_id(config, release_id)
    legacy_index = release_id == LEGACY_RELEASE_ID

    if (
        _bm25_index is not None
        and _bm25_cache_artifact_id == artifact_id
        and (not legacy_index or (time.time() - _bm25_loaded_at) < _BM25_TTL)
    ):
        return _bm25_index

    if _bm25_failed_artifact_id == artifact_id and time.time() < _bm25_load_failed_until:
        return None

    if not config.bm25_index_bucket:
        logger.warning("BM25_INDEX_BUCKET not configured")
        _bm25_load_failed_until = time.time() + _BM25_RETRY_INTERVAL
        _bm25_failed_artifact_id = artifact_id
        return None

    try:
        safe_artifact_id = "".join(c for c in artifact_id if c.isalnum() or c in "-_")
        local_path = f"/tmp/bm25_index_{safe_artifact_id}.json"  # noqa: S108
        client = boto3.client("s3", region_name=config.aws_region)
        client.download_file(config.bm25_index_bucket, config.bm25_index_key, local_path)

        with open(local_path) as f:
            raw = json.load(f)

        _validate_release_index(raw, config, release_id, artifact_id, legacy_index)
        _bm25_index = _reconstruct_index(raw, artifact_id)
        _bm25_cache_artifact_id = artifact_id
        _bm25_loaded_at = time.time()
        _bm25_failed_artifact_id = None
        _bm25_load_failed_until = 0

        logger.info(
            "BM25 index loaded",
            extra={
                "num_chunks": len(_bm25_index["chunk_ids"]),
                "release_id": release_id,
                "retrieval_artifact_id": artifact_id,
            },
        )
    except Exception:
        logger.exception("Failed to load BM25 index from S3", extra={"release_id": release_id})
        _bm25_load_failed_until = time.time() + _BM25_RETRY_INTERVAL
        _bm25_failed_artifact_id = artifact_id
        return None
    else:
        return _bm25_index


def get_cached_chunk_metadata(s3_key: str, retrieval_snapshot=None) -> dict:
    """Return release-pinned metadata for a chunk from the already-loaded BM25 index.

    Never triggers a download; returns ``{}`` when the in-memory index doesn't match the snapshot.
    """
    index = _bm25_index
    if index is None or not s3_key:
        return {}

    config = retrieval_snapshot or get_config()
    artifact_id = _artifact_id(config, _release_id(config))
    # Stale cache must degrade to "no metadata", not to wrong metadata.
    if index.get("retrieval_artifact_id") != artifact_id:
        return {}

    metadata = index.get("metadata_by_key", {}).get(s3_key)
    return dict(metadata) if metadata else {}


def bm25_search(query: str, top_k: int = 10, retrieval_snapshot=None) -> list[dict]:
    """Search the BM25 index for relevant chunks."""
    index = _load_index(retrieval_snapshot)
    if index is None:
        return []

    tokens = tokenize(query)
    if not tokens:
        return []

    scores = index["bm25"].get_scores(tokens)
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score <= 0:
            break
        results.append({
            "chunk_id": index["chunk_ids"][idx],
            "score": score,
            "content": index["chunk_contents"][idx],
            "metadata": index["chunk_metadata"][idx],
            # Report the request-scoped release, not the one that built the reusable artifact first.
            "release_id": _release_id(retrieval_snapshot or get_config()),
        })

    return results
