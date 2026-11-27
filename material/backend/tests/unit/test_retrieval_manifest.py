import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator import retrieval_manifest as resolver
from bm25_shared.retrieval_manifest import (
    RetrievalManifest,
    RetrievalManifestError,
    derive_release_id,
    derive_retrieval_artifact_fingerprint,
    derive_retrieval_artifact_id,
)
from bm25_shared.tokenizer import TOKENIZER_REVISION

RELEASE_A = derive_release_id("1.105.0", "v1.104.0", "v1.103.0")
RELEASE_B = derive_release_id("1.105.0", "v1.104.0", "v1.103.1")


def manifest_payload(release_id=None, **overrides):
    payload = {
        "schema_version": 3,
        "version": "1.105.0",
        "data_artifact_version": "v1.104.0",
        "etl_version": "v1.103.0",
        "knowledge_base_id": "KB1234567890",
        "data_source_id": "DS1234567890",
        "raw_bucket": "qa-etl-source",
        "raw_prefix": "releases/v1.104.0/",
        "processed_bucket": "qa-retrieval-green",
        "bm25_bucket": "qa-retrieval-green",
        "bm25_tokenizer_revision": TOKENIZER_REVISION,
        "etl_image_digest": f"sha256:{'d' * 64}",
        "chatbot_image_digest": f"sha256:{'c' * 64}",
    }
    payload.update(overrides)
    payload["release_id"] = release_id or derive_release_id(
        payload["version"], payload["data_artifact_version"], payload["etl_version"]
    )
    payload.setdefault(
        "retrieval_artifact_id",
        derive_retrieval_artifact_id(
            payload["data_artifact_version"],
            payload["etl_version"],
            payload["bm25_tokenizer_revision"],
        ),
    )
    payload.setdefault(
        "retrieval_artifact_fingerprint",
        derive_retrieval_artifact_fingerprint(
            payload["data_artifact_version"],
            payload["etl_version"],
            payload["bm25_tokenizer_revision"],
        ),
    )
    payload.setdefault("processed_prefix", f"processed/releases/{payload['retrieval_artifact_id']}/")
    payload.setdefault("bm25_key", f"bm25_index/releases/{payload['retrieval_artifact_id']}/index.json")
    return payload


def runtime_config(**overrides):
    values = {
        "aws_region": "eu-central-1",
        "retrieval_manifest_parameter": "/qa/renate/retrieval/active-manifest",
        "knowledge_base_id": "LEGACYKB",
        "bm25_index_bucket": "legacy-bucket",
        "bm25_index_key": "bm25_index/index.json",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def clear_resolver_cache():
    resolver.reset_retrieval_manifest_cache()
    yield
    resolver.reset_retrieval_manifest_cache()


def test_manifest_validates_exact_schema_and_immutable_key():
    manifest = RetrievalManifest.from_dict(manifest_payload())

    assert manifest.release_id == RELEASE_A
    assert manifest.bm25_key.endswith(f"/{manifest.artifact_id}/index.json")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"schema_version": 1}, "schema_version"),
        ({"schema_version": True}, "schema_version"),
        ({"release_id": "green"}, "release_id"),
        ({"bm25_key": "bm25_index/index.json"}, "bm25_key"),
        ({"etl_version": "main"}, "etl_version"),
        ({"raw_prefix": "IN/"}, "raw_prefix"),
        ({"processed_prefix": "docs/"}, "processed_prefix"),
        ({"processed_bucket": "other-bucket"}, "processed_bucket"),
        ({"etl_image_digest": "latest"}, "etl_image_digest"),
    ],
)
def test_manifest_rejects_invalid_coordinates(override, message):
    with pytest.raises(RetrievalManifestError, match=message):
        RetrievalManifest.from_dict(manifest_payload(**override))


def test_manifest_rejects_unknown_fields():
    with pytest.raises(RetrievalManifestError, match="unknown fields"):
        RetrievalManifest.from_dict({**manifest_payload(), "slot": "green"})


def test_v2_rollback_manifest_remains_readable_and_uses_release_as_artifact_identity():
    payload = manifest_payload()
    payload["schema_version"] = 2
    for field in ("retrieval_artifact_id", "retrieval_artifact_fingerprint", "chatbot_image_digest"):
        payload.pop(field)
    payload["processed_prefix"] = f"processed/releases/{payload['release_id']}/"
    payload["bm25_key"] = f"bm25_index/releases/{payload['release_id']}/index.json"

    manifest = RetrievalManifest.from_dict(payload)

    assert manifest.artifact_id == manifest.release_id
    assert manifest.to_dict() == payload


def test_chatbot_only_release_reuses_artifact_identity_and_storage_keys():
    first = RetrievalManifest.from_dict(manifest_payload(version="1.105.0"))
    successor = RetrievalManifest.from_dict(manifest_payload(version="1.105.1"))

    assert first.release_id != successor.release_id
    assert first.artifact_id == successor.artifact_id
    assert first.processed_prefix == successor.processed_prefix
    assert first.bm25_key == successor.bm25_key


def test_manifest_rejects_artifact_identity_from_different_etl_coordinate():
    wrong_artifact = derive_retrieval_artifact_id("v1.104.0", "v1.103.1", TOKENIZER_REVISION)
    with pytest.raises(RetrievalManifestError, match="retrieval_artifact_id"):
        RetrievalManifest.from_dict(manifest_payload(retrieval_artifact_id=wrong_artifact))


def test_resolver_caches_one_complete_manifest_for_60_seconds():
    client = MagicMock()
    client.get_parameter.side_effect = [
        {"Parameter": {"Value": json.dumps(manifest_payload(RELEASE_A))}},
        {"Parameter": {"Value": json.dumps(manifest_payload(etl_version="v1.103.1"))}},
    ]

    with (
        patch.object(resolver, "_get_ssm_client", return_value=client),
        patch.object(resolver.time, "monotonic", side_effect=[100.0, 159.9, 160.1]),
    ):
        first = resolver.resolve_retrieval_snapshot(runtime_config())
        cached = resolver.resolve_retrieval_snapshot(runtime_config())
        refreshed = resolver.resolve_retrieval_snapshot(runtime_config())

    assert first.release_id == RELEASE_A
    assert cached is first
    assert refreshed.release_id == RELEASE_B
    assert client.get_parameter.call_count == 2


def test_release_id_is_the_deterministic_three_coordinate_fingerprint():
    assert (
        derive_release_id("1.83.3", "v1.83.3-qa-blue-baseline", "v1.83.3-qa-blue-baseline")
        == "sha256-4a68e8e7f1bfa474a9d2c955a0c208e5229fbfa8c723a554d9266e165958325a"
    )


def test_release_id_changes_when_only_the_faq_component_of_data_changes():
    faq_a = "v1.92.0-data.1"
    faq_b = "v1.92.0-data.2"
    assert derive_release_id("1.109.0", faq_a, "v1.108.3") != derive_release_id("1.109.0", faq_b, "v1.108.3")


def test_manifest_rejects_a_release_id_from_different_coordinates():
    with pytest.raises(RetrievalManifestError, match="does not match"):
        RetrievalManifest.from_dict(manifest_payload(release_id=RELEASE_B))


def test_configured_missing_selector_fails_closed_without_using_legacy_coordinates():
    client = MagicMock()
    client.get_parameter.side_effect = RuntimeError("ParameterNotFound")

    with (
        patch.object(resolver, "_get_ssm_client", return_value=client),
        pytest.raises(resolver.RetrievalManifestUnavailableError, match="active-manifest"),
    ):
        resolver.resolve_retrieval_snapshot(runtime_config())

    client.get_parameter.assert_called_once()


def test_configured_selector_retries_after_fail_closed_error():
    client = MagicMock()
    client.get_parameter.side_effect = [
        RuntimeError("ParameterNotFound"),
        {"Parameter": {"Value": json.dumps(manifest_payload())}},
    ]

    with patch.object(resolver, "_get_ssm_client", return_value=client):
        with pytest.raises(resolver.RetrievalManifestUnavailableError):
            resolver.resolve_retrieval_snapshot(runtime_config())
        recovered = resolver.resolve_retrieval_snapshot(runtime_config())

    assert recovered.release_id == RELEASE_A
    assert recovered.legacy_fallback is False
    assert client.get_parameter.call_count == 2


def test_failed_refresh_retains_last_validated_manifest_instead_of_mixing_with_legacy():
    client = MagicMock()
    client.get_parameter.side_effect = [
        {"Parameter": {"Value": json.dumps(manifest_payload())}},
        {"Parameter": {"Value": "not-json"}},
    ]

    with (
        patch.object(resolver, "_get_ssm_client", return_value=client),
        patch.object(resolver.time, "monotonic", side_effect=[100.0, 161.0]),
    ):
        first = resolver.resolve_retrieval_snapshot(runtime_config())
        after_failed_refresh = resolver.resolve_retrieval_snapshot(runtime_config())

    assert after_failed_refresh is first
    assert after_failed_refresh.legacy_fallback is False


def test_request_config_is_a_frozen_coordinate_copy():
    config = runtime_config(retrieval_manifest_parameter="")
    request_config = resolver.snapshot_retrieval_config(config)
    config.knowledge_base_id = "CHANGED-MID-REQUEST"
    config.bm25_index_key = "changed.json"

    assert request_config.knowledge_base_id == "LEGACYKB"
    assert request_config.bm25_index_key == "bm25_index/index.json"
    assert request_config.retrieval_release_id == resolver.LEGACY_RELEASE_ID
    assert request_config.retrieval_artifact_id == resolver.LEGACY_RELEASE_ID
