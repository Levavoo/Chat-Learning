"""Validation and identity helpers for atomic hybrid-retrieval manifests."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = frozenset({2, SCHEMA_VERSION})
BM25_RELEASES_PREFIX = "bm25_index/releases/"
RAW_RELEASES_PREFIX = "releases/"
PROCESSED_RELEASES_PREFIX = "processed/releases/"
RETRIEVAL_MANIFESTS_PREFIX = "retrieval-manifests/releases/"

_SHA256_ID_RE = re.compile(r"^sha256-[0-9a-f]{64}$")
_SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_APP_VERSION_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$")
_PROMOTED_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?$")
_S3_BUCKET_RE = re.compile(r"^(?!\d+\.\d+\.\d+\.\d+$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_COORDINATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")

_V2_FIELDS = {
    "schema_version",
    "release_id",
    "version",
    "data_artifact_version",
    "etl_version",
    "knowledge_base_id",
    "data_source_id",
    "raw_bucket",
    "raw_prefix",
    "processed_bucket",
    "processed_prefix",
    "bm25_bucket",
    "bm25_key",
    "bm25_tokenizer_revision",
    "etl_image_digest",
}
_V3_FIELDS = _V2_FIELDS | {
    "retrieval_artifact_id",
    "retrieval_artifact_fingerprint",
    "chatbot_image_digest",
}


class RetrievalManifestError(ValueError):
    """Raised when a retrieval manifest violates its versioned schema."""


def _validate_fields(payload: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RetrievalManifestError("retrieval manifest must be a JSON object")
    missing = sorted(expected - set(payload))
    unknown = sorted(set(payload) - expected)
    if missing:
        raise RetrievalManifestError(f"retrieval manifest is missing fields: {', '.join(missing)}")
    if unknown:
        raise RetrievalManifestError(f"retrieval manifest has unknown fields: {', '.join(unknown)}")
    return payload


def _schema_version(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise RetrievalManifestError("retrieval manifest must be a JSON object")
    version = payload.get("schema_version")
    if type(version) is not int or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RetrievalManifestError(f"unsupported retrieval manifest schema_version: {version!r}")
    return version


def _validate_versions(payload: dict[str, Any]) -> None:
    if not _APP_VERSION_RE.fullmatch(payload["version"]):
        raise RetrievalManifestError("version must be a semantic version")
    for field in ("data_artifact_version", "etl_version"):
        if not _PROMOTED_VERSION_RE.fullmatch(payload[field]):
            raise RetrievalManifestError(f"{field} must be an immutable v-prefixed semantic version")


def _validate_release_identity(payload: dict[str, Any]) -> None:
    release_id = payload["release_id"]
    if not _SHA256_ID_RE.fullmatch(release_id):
        raise RetrievalManifestError("release_id must be sha256- followed by 64 lowercase hex characters")
    expected_release_id = derive_release_id(
        payload["version"], payload["data_artifact_version"], payload["etl_version"]
    )
    if release_id != expected_release_id:
        raise RetrievalManifestError(
            f"release_id does not match the promoted coordinates; expected {expected_release_id}"
        )


def _validate_artifact_identity(payload: dict[str, Any]) -> None:
    artifact_id = payload["retrieval_artifact_id"]
    fingerprint = payload["retrieval_artifact_fingerprint"]
    expected_id = derive_retrieval_artifact_id(
        payload["data_artifact_version"],
        payload["etl_version"],
        payload["bm25_tokenizer_revision"],
    )
    expected_fingerprint = derive_retrieval_artifact_fingerprint(
        payload["data_artifact_version"],
        payload["etl_version"],
        payload["bm25_tokenizer_revision"],
    )
    if artifact_id != expected_id:
        raise RetrievalManifestError(
            f"retrieval_artifact_id does not match data, ETL, and tokenizer coordinates; expected {expected_id}"
        )
    if fingerprint != expected_fingerprint:
        raise RetrievalManifestError(
            "retrieval_artifact_fingerprint does not match data, ETL, and tokenizer coordinates; "
            f"expected {expected_fingerprint}"
        )


def _validate_storage_coordinates(payload: dict[str, Any]) -> None:
    for field in ("raw_bucket", "processed_bucket", "bm25_bucket"):
        if not _S3_BUCKET_RE.fullmatch(payload[field]):
            raise RetrievalManifestError(f"{field} is not a valid S3 bucket name")
    if payload["processed_bucket"] != payload["bm25_bucket"]:
        raise RetrievalManifestError("processed_bucket must equal bm25_bucket")
    expected_raw_prefix = immutable_raw_prefix(payload["data_artifact_version"])
    if payload["raw_prefix"] != expected_raw_prefix:
        raise RetrievalManifestError(f"raw_prefix must equal {expected_raw_prefix}")

    storage_id = payload["retrieval_artifact_id"] if payload["schema_version"] >= 3 else payload["release_id"]
    expected_processed_prefix = immutable_processed_prefix(storage_id)
    if payload["processed_prefix"] != expected_processed_prefix:
        raise RetrievalManifestError(f"processed_prefix must equal {expected_processed_prefix}")
    expected_key = immutable_bm25_key(storage_id)
    if payload["bm25_key"] != expected_key:
        raise RetrievalManifestError(f"bm25_key must equal {expected_key}")
    if not _SHA256_DIGEST_RE.fullmatch(payload["etl_image_digest"]):
        raise RetrievalManifestError("etl_image_digest must be an immutable sha256 digest")
    if payload["schema_version"] >= 3 and not _SHA256_DIGEST_RE.fullmatch(payload["chatbot_image_digest"]):
        raise RetrievalManifestError("chatbot_image_digest must be an immutable sha256 digest")


def _validate_coordinates(payload: dict[str, Any]) -> None:
    for field in ("knowledge_base_id", "data_source_id", "bm25_tokenizer_revision"):
        if not _COORDINATE_RE.fullmatch(payload[field]):
            raise RetrievalManifestError(f"{field} contains unsupported characters")
    _validate_release_identity(payload)
    if payload["schema_version"] >= 3:
        _validate_artifact_identity(payload)
    _validate_storage_coordinates(payload)


@dataclass(frozen=True, slots=True)
class RetrievalManifest:
    """One immutable, coherent semantic + lexical retrieval release.

    Schema v2 remains readable so the #491 blue and green rollback manifests
    stay valid. Schema v3 separates the application release identity from the
    reusable retrieval-artifact identity, enabling a chatbot-only promotion to
    reuse an unchanged processed corpus and BM25 index.
    """

    schema_version: int
    release_id: str
    version: str
    data_artifact_version: str
    etl_version: str
    knowledge_base_id: str
    data_source_id: str
    raw_bucket: str
    raw_prefix: str
    processed_bucket: str
    processed_prefix: str
    bm25_bucket: str
    bm25_key: str
    bm25_tokenizer_revision: str
    etl_image_digest: str
    retrieval_artifact_id: str | None = None
    retrieval_artifact_fingerprint: str | None = None
    chatbot_image_digest: str | None = None

    @property
    def artifact_id(self) -> str:
        """Identity used for processed and BM25 artifacts and runtime caching."""
        return self.retrieval_artifact_id or self.release_id

    @classmethod
    def from_json(cls, value: str) -> "RetrievalManifest":
        """Parse and validate one JSON manifest value."""
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RetrievalManifestError("retrieval manifest must be valid JSON") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Any) -> "RetrievalManifest":
        """Validate a decoded v2 or v3 manifest with an exact field set."""
        schema_version = _schema_version(payload)
        expected = _V3_FIELDS if schema_version >= 3 else _V2_FIELDS
        payload = _validate_fields(payload, expected)

        for field in expected - {"schema_version"}:
            if not isinstance(payload[field], str) or not payload[field]:
                raise RetrievalManifestError(f"retrieval manifest field {field} must be a non-empty string")

        _validate_versions(payload)
        _validate_coordinates(payload)

        values = dict(payload)
        if schema_version == 2:
            values.update(
                retrieval_artifact_id=None,
                retrieval_artifact_fingerprint=None,
                chatbot_image_digest=None,
            )
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        """Return the manifest in its original versioned wire shape."""
        payload = asdict(self)
        if self.schema_version == 2:
            for field in _V3_FIELDS - _V2_FIELDS:
                payload.pop(field)
        return payload


def _validate_sha256_id(value: str, field: str) -> None:
    if not _SHA256_ID_RE.fullmatch(value):
        raise RetrievalManifestError(f"{field} must be sha256- followed by 64 lowercase hex characters")


def immutable_bm25_key(artifact_id: str) -> str:
    """Return the canonical BM25 object key for an immutable artifact."""
    _validate_sha256_id(artifact_id, "retrieval artifact ID")
    return f"{BM25_RELEASES_PREFIX}{artifact_id}/index.json"


def immutable_raw_prefix(data_artifact_version: str) -> str:
    """Return the canonical immutable raw prefix for a data coordinate."""
    if not _PROMOTED_VERSION_RE.fullmatch(data_artifact_version):
        raise RetrievalManifestError("data_artifact_version must be an immutable v-prefixed semantic version")
    return f"{RAW_RELEASES_PREFIX}{data_artifact_version}/"


def immutable_processed_prefix(artifact_id: str) -> str:
    """Return the canonical immutable processed-artifact prefix."""
    _validate_sha256_id(artifact_id, "retrieval artifact ID")
    return f"{PROCESSED_RELEASES_PREFIX}{artifact_id}/"


def immutable_manifest_key(release_id: str) -> str:
    """Return the write-once object key for a complete release manifest."""
    _validate_sha256_id(release_id, "release_id")
    return f"{RETRIEVAL_MANIFESTS_PREFIX}{release_id}.json"


def derive_release_id(version: str, data_artifact_version: str, etl_version: str) -> str:
    """Derive the release fingerprint from the exact three-line promotion pin."""
    canonical = f"version={version}\ndata_artifact_version={data_artifact_version}\netl_version={etl_version}\n"
    return f"sha256-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _artifact_digest(data_artifact_version: str, etl_version: str, tokenizer_revision: str) -> str:
    canonical = (
        f"data_artifact_version={data_artifact_version}\n"
        f"etl_version={etl_version}\n"
        f"bm25_tokenizer_revision={tokenizer_revision}\n"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_retrieval_artifact_id(data_artifact_version: str, etl_version: str, tokenizer_revision: str) -> str:
    """Derive the path-safe identity of reusable retrieval artifacts."""
    return f"sha256-{_artifact_digest(data_artifact_version, etl_version, tokenizer_revision)}"


def derive_retrieval_artifact_fingerprint(data_artifact_version: str, etl_version: str, tokenizer_revision: str) -> str:
    """Derive the digest-form attestation for reusable retrieval artifacts."""
    return f"sha256:{_artifact_digest(data_artifact_version, etl_version, tokenizer_revision)}"
