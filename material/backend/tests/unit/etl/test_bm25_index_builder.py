import json
import re
import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from bm25_shared.retrieval_manifest import (
    derive_release_id,
    derive_retrieval_artifact_fingerprint,
    derive_retrieval_artifact_id,
)
from bm25_shared.tokenizer import TOKENIZER_REVISION
from etl.bm25_index_builder import build_index, handler, list_chunk_keys

# Pre-#700 in-memory FAQ enrichment, reproduced so the parity guard can prove
# the complete-sidecar semantic header is byte-identical to the header the
# deleted enrichment produced.
_LEGACY_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


def _legacy_enrich_faq_metadata(metadata: dict, body: str) -> dict:
    brochure = (metadata.get("brochure_number") or "").lower()
    if not brochure.startswith("faq"):
        return metadata
    question = ""
    for match in _LEGACY_HEADING_RE.finditer(body):
        candidate = match.group(1).strip()
        if " > " in candidate:
            continue
        question = candidate
        break
    enriched = dict(metadata)
    enriched.setdefault("category", "FAQ")
    if question:
        enriched["section_title"] = question
        enriched["title"] = f"FAQ — {question}"
    return enriched


class TestListChunkKeys(unittest.TestCase):
    def test_lists_md_files_only(self):
        """Only .md files; metadata sidecars excluded."""
        client = MagicMock()
        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "docs/a.md"},
                {"Key": "docs/a.md.metadata.json"},
                {"Key": "docs/b.md"},
                {"Key": "docs/config.json"},
            ],
            "IsTruncated": False,
        }

        keys = list_chunk_keys(client, "bucket", "docs/")
        self.assertEqual(keys, ["docs/a.md", "docs/b.md"])

    def test_handles_pagination(self):
        client = MagicMock()
        client.list_objects_v2.side_effect = [
            {
                "Contents": [{"Key": "docs/a.md"}],
                "IsTruncated": True,
                "NextContinuationToken": "token1",
            },
            {
                "Contents": [{"Key": "docs/b.md"}],
                "IsTruncated": False,
            },
        ]

        keys = list_chunk_keys(client, "bucket", "docs/")
        self.assertEqual(keys, ["docs/a.md", "docs/b.md"])
        self.assertEqual(client.list_objects_v2.call_count, 2)

    def test_empty_bucket(self):
        client = MagicMock()
        client.list_objects_v2.return_value = {"IsTruncated": False}

        keys = list_chunk_keys(client, "bucket", "docs/")
        self.assertEqual(keys, [])


class TestBuildIndex(unittest.TestCase):
    @patch("etl.bm25_index_builder.boto3")
    def test_builds_and_uploads_json_index(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client

        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "docs/a.md"},
                {"Key": "docs/b.md"},
            ],
            "IsTruncated": False,
        }

        def mock_get_object(Bucket, Key):
            content = {
                "docs/a.md": "Rente Berechnung Altersvorsorge",
                "docs/b.md": "Rehabilitation Medizin Therapie",
            }
            body = MagicMock()
            body.read.return_value = content[Key].encode("utf-8")
            return {"Body": body}

        client.get_object.side_effect = mock_get_object

        num = build_index("bucket", "docs/", "bm25_index/index.json")

        self.assertEqual(num, 2)
        client.upload_fileobj.assert_called_once()

        uploaded_buf = client.upload_fileobj.call_args[0][0]
        data = json.loads(uploaded_buf.read().decode("utf-8"))
        self.assertEqual(data["chunk_ids"], ["docs/a.md", "docs/b.md"])
        self.assertEqual(len(data["corpus"]), 2)
        self.assertEqual(len(data["chunk_contents"]), 2)
        self.assertEqual(data["release_id"], "legacy")
        self.assertEqual(data["bm25_tokenizer_revision"], TOKENIZER_REVISION)

    @patch("etl.bm25_index_builder.boto3")
    def test_returns_zero_when_no_chunks(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client
        client.list_objects_v2.return_value = {"IsTruncated": False}

        num = build_index("bucket", "docs/", "bm25_index/index.json")
        self.assertEqual(num, 0)
        client.upload_fileobj.assert_not_called()

    @patch("etl.bm25_index_builder.boto3")
    def test_strips_yaml_frontmatter(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client

        client.list_objects_v2.return_value = {
            "Contents": [{"Key": "docs/a.md"}],
            "IsTruncated": False,
        }

        body = MagicMock()
        body.read.return_value = b"---\ntitle: Test\n---\nRente Berechnung"
        client.get_object.return_value = {"Body": body}

        num = build_index("bucket", "docs/", "bm25_index/index.json")
        self.assertEqual(num, 1)

        uploaded_buf = client.upload_fileobj.call_args[0][0]
        data = json.loads(uploaded_buf.read().decode("utf-8"))
        self.assertNotIn("title", data["chunk_contents"][0])

    @patch("etl.bm25_index_builder.boto3")
    def test_immutable_release_uses_atomic_write_once_precondition(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client
        release_id = f"sha256-{'a' * 64}"
        processed_prefix = f"processed/releases/{release_id}/"
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": f"{processed_prefix}docs/a.md"}],
            "IsTruncated": False,
        }
        body = MagicMock()
        body.read.return_value = b"Rente Berechnung"
        client.get_object.return_value = {"Body": body}
        index_key = f"bm25_index/releases/{release_id}/index.json"

        num = build_index(
            "bucket",
            f"{processed_prefix}docs/",
            index_key,
            release_id=release_id,
            tokenizer_revision=TOKENIZER_REVISION,
            chunk_id_base_prefix=processed_prefix,
        )

        self.assertEqual(num, 1)
        client.upload_fileobj.assert_not_called()
        client.put_object.assert_called_once()
        put = client.put_object.call_args.kwargs
        self.assertEqual(put["Bucket"], "bucket")
        self.assertEqual(put["Key"], index_key)
        self.assertEqual(put["IfNoneMatch"], "*")
        self.assertEqual(put["ChecksumAlgorithm"], "SHA256")
        self.assertEqual(put["Tagging"], "renate%3Aretention=pinned")
        data = json.loads(put["Body"])
        self.assertEqual(data["release_id"], release_id)
        self.assertEqual(data["chunk_ids"], ["docs/a.md"])
        self.assertEqual(data["chunk_contents"], ["Rente Berechnung"])

    @patch("etl.bm25_index_builder.boto3")
    def test_identical_immutable_release_is_an_idempotent_retry(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client
        release_id = f"sha256-{'a' * 64}"
        processed_prefix = f"processed/releases/{release_id}/"
        index_key = f"bm25_index/releases/{release_id}/index.json"
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": f"{processed_prefix}docs/a.md"}],
            "IsTruncated": False,
        }
        chunk_body = MagicMock()
        chunk_body.read.return_value = b"Rente Berechnung"

        def get_object(*, Bucket, Key):
            if Key == f"{processed_prefix}docs/a.md":
                return {"Body": chunk_body}
            if Key.endswith(".metadata.json"):
                raise KeyError(Key)
            existing = MagicMock()
            existing.read.return_value = client.put_object.call_args.kwargs["Body"]
            return {"Body": existing}

        client.get_object.side_effect = get_object
        client.put_object.side_effect = ClientError(
            {
                "Error": {"Code": "PreconditionFailed", "Message": "exists"},
                "ResponseMetadata": {"HTTPStatusCode": 412},
            },
            "PutObject",
        )

        num = build_index(
            "bucket",
            f"{processed_prefix}docs/",
            index_key,
            release_id=release_id,
            tokenizer_revision=TOKENIZER_REVISION,
            chunk_id_base_prefix=processed_prefix,
        )

        self.assertEqual(num, 1)
        self.assertEqual(client.get_object.call_count, 3)

    @patch("etl.bm25_index_builder.boto3")
    def test_divergent_immutable_release_still_fails_closed(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client
        release_id = f"sha256-{'a' * 64}"
        processed_prefix = f"processed/releases/{release_id}/"
        index_key = f"bm25_index/releases/{release_id}/index.json"
        client.list_objects_v2.return_value = {
            "Contents": [{"Key": f"{processed_prefix}docs/a.md"}],
            "IsTruncated": False,
        }
        chunk_body = MagicMock()
        chunk_body.read.return_value = b"Rente Berechnung"
        existing = MagicMock()
        existing.read.return_value = b"divergent"

        def get_object(*, Bucket, Key):
            if Key == f"{processed_prefix}docs/a.md":
                return {"Body": chunk_body}
            if Key.endswith(".metadata.json"):
                raise KeyError(Key)
            return {"Body": existing}

        client.get_object.side_effect = get_object
        client.put_object.side_effect = ClientError(
            {
                "Error": {"Code": "PreconditionFailed", "Message": "exists"},
                "ResponseMetadata": {"HTTPStatusCode": 412},
            },
            "PutObject",
        )

        with self.assertRaisesRegex(ValueError, "immutable BM25 index already differs"):
            build_index(
                "bucket",
                f"{processed_prefix}docs/",
                index_key,
                release_id=release_id,
                tokenizer_revision=TOKENIZER_REVISION,
                chunk_id_base_prefix=processed_prefix,
            )


class TestHandlerRouting(unittest.TestCase):
    """Tests for the updated handler: Delete guard + SQS/direct rebuild path."""

    @patch("etl.bm25_index_builder.build_index")
    @patch.dict(
        "os.environ",
        {"BM25_BUCKET": "bucket", "BM25_CHUNK_PREFIX": "docs/", "BM25_INDEX_KEY": "bm25_index/index.json"},
    )
    def test_sqs_event_builds_index_and_returns_num_chunks(self, mock_build):
        mock_build.return_value = 7
        result = handler({"Records": [{"body": "{}"}]}, None)
        mock_build.assert_called_once_with("bucket", "docs/", "bm25_index/index.json")
        self.assertEqual(result, {"NumChunks": 7})

    @patch("etl.bm25_index_builder.build_index")
    @patch.dict(
        "os.environ",
        {"BM25_BUCKET": "bucket", "BM25_CHUNK_PREFIX": "docs/", "BM25_INDEX_KEY": "bm25_index/index.json"},
    )
    def test_direct_operator_invoke_returns_num_chunks(self, mock_build):
        mock_build.return_value = 42
        result = handler({"source": "operator"}, None)
        mock_build.assert_called_once_with("bucket", "docs/", "bm25_index/index.json")
        self.assertEqual(result, {"NumChunks": 42})

    @patch("etl.bm25_index_builder.build_index")
    def test_cfn_delete_is_noop(self, mock_build):
        """CFN Delete must not rebuild (compatibility guard)."""
        result = handler({"RequestType": "Delete"}, None)
        mock_build.assert_not_called()
        self.assertIsNone(result)

    @patch("etl.bm25_index_builder.build_index")
    @patch.dict(
        "os.environ",
        {"BM25_BUCKET": "bucket"},
    )
    def test_cfn_create_would_rebuild_if_sent(self, mock_build):
        """Non-Delete RequestType routes to rebuild (safe behaviour for the removed resource)."""
        mock_build.return_value = 3
        result = handler({"RequestType": "Create"}, None)
        mock_build.assert_called_once()
        self.assertEqual(result, {"NumChunks": 3})

    @patch("etl.bm25_index_builder.build_index")
    @patch.dict(
        "os.environ",
        {
            "BM25_BUCKET": "qa-retrieval-green",
            "BM25_IMMUTABLE_ONLY": "true",
            "RETRIEVAL_KNOWLEDGE_BASE_ID": "KB1234567890",
            "RETRIEVAL_DATA_SOURCE_ID": "DS1234567890",
        },
    )
    def test_manifest_build_writes_immutable_self_contained_release(self, mock_build):
        release_id = derive_release_id("1.105.0", "v1.104.0", "v1.103.0")
        artifact_id = derive_retrieval_artifact_id("v1.104.0", "v1.103.0", TOKENIZER_REVISION)
        manifest = {
            "schema_version": 3,
            "release_id": release_id,
            "retrieval_artifact_id": artifact_id,
            "retrieval_artifact_fingerprint": derive_retrieval_artifact_fingerprint(
                "v1.104.0", "v1.103.0", TOKENIZER_REVISION
            ),
            "version": "1.105.0",
            "data_artifact_version": "v1.104.0",
            "etl_version": "v1.103.0",
            "knowledge_base_id": "KB1234567890",
            "data_source_id": "DS1234567890",
            "raw_bucket": "qa-etl-source",
            "raw_prefix": "releases/v1.104.0/",
            "processed_bucket": "qa-retrieval-green",
            "processed_prefix": f"processed/releases/{artifact_id}/",
            "bm25_bucket": "qa-retrieval-green",
            "bm25_key": f"bm25_index/releases/{artifact_id}/index.json",
            "bm25_tokenizer_revision": TOKENIZER_REVISION,
            "etl_image_digest": f"sha256:{'d' * 64}",
            "chatbot_image_digest": f"sha256:{'c' * 64}",
        }
        mock_build.return_value = 17

        result = handler({"retrieval_manifest": manifest}, None)

        mock_build.assert_called_once_with(
            "qa-retrieval-green",
            f"processed/releases/{artifact_id}/docs/",
            manifest["bm25_key"],
            release_id=release_id,
            retrieval_artifact_id=artifact_id,
            tokenizer_revision=TOKENIZER_REVISION,
            chunk_id_base_prefix=f"processed/releases/{artifact_id}/",
        )
        self.assertEqual(result["ReleaseId"], release_id)
        self.assertEqual(result["RetrievalArtifactId"], artifact_id)
        self.assertEqual(result["NumChunks"], 17)

    @patch("etl.bm25_index_builder.build_index")
    @patch.dict("os.environ", {"BM25_BUCKET": "qa-retrieval-green", "BM25_IMMUTABLE_ONLY": "true"})
    def test_green_event_cannot_write_a_mutable_index(self, mock_build):
        result = handler({"Records": [{"body": "{}"}]}, None)

        mock_build.assert_not_called()
        self.assertEqual(result, {"Skipped": "retrieval_manifest required"})


class TestSemanticHeader(unittest.TestCase):
    def test_includes_keywords_and_synonyms(self):
        from etl.bm25_index_builder import _semantic_header

        metadata = {
            "name": "Merkblatt Befreiung",
            "brochure_number": "V0017",
            "category": "Merkblatt",
            "section_title": "Befreiung Handwerker",
            "keywords": "Versicherungspflicht, Handwerker, Befreiung",
            "colloquial_terms": "muss ich zahlen, Handwerker Rente",
            "enriched": True,
        }
        header = _semantic_header(metadata)
        assert "Schlüsselwörter: Versicherungspflicht, Handwerker, Befreiung" in header
        assert "Synonyme: muss ich zahlen, Handwerker Rente" in header
        assert "Abschnitt: Befreiung Handwerker" in header

    def test_omits_empty_keywords(self):
        from etl.bm25_index_builder import _semantic_header

        metadata = {"name": "Test", "brochure_number": "B01"}
        header = _semantic_header(metadata)
        assert "Schlüsselwörter" not in header
        assert "Synonyme" not in header

    def test_dita_keywords_excluded_without_colloquial_terms(self):
        """DITA keywords alone don't appear in header."""
        from etl.bm25_index_builder import _semantic_header

        metadata = {"name": "Test", "brochure_number": "B01", "keywords": "Rente, Altersrente"}
        header = _semantic_header(metadata)
        assert "Schlüsselwörter" not in header


class TestFaqSidecarMetadata(unittest.TestCase):
    """#700: build_index consumes the canonical FAQ sidecar directly (no in-memory enrich)."""

    _CANONICAL_FAQ_METADATA: ClassVar[dict[str, str]] = {
        "chunk_type": "faq",
        "category": "FAQ",
        "name": "FAQ Rentenbeginn",
        "section_title": "Wann kann ich in Rente gehen?",
        "title": "FAQ — Wann kann ich in Rente gehen?",
        "brochure_number": "faq-a-und-b",
        "brochure_url": "https://drv.de/faq-a-und-b.html#content-1",
    }

    @patch("etl.bm25_index_builder.boto3")
    def test_build_index_uses_sidecar_metadata_verbatim(self, mock_boto3):
        client = MagicMock()
        mock_boto3.client.return_value = client
        key = "docs/faq-a-und-b/faq-a-und-b_0000.md"
        client.list_objects_v2.return_value = {"Contents": [{"Key": key}], "IsTruncated": False}

        def get_object(*, Bucket, Key):
            body = MagicMock()
            if Key == key:
                body.read.return_value = b"# Wann kann ich in Rente gehen?\n\nAntwort text."
            elif Key == f"{key}.metadata.json":
                body.read.return_value = json.dumps({"metadataAttributes": self._CANONICAL_FAQ_METADATA}).encode(
                    "utf-8"
                )
            else:
                raise AssertionError(Key)
            return {"Body": body}

        client.get_object.side_effect = get_object

        num = build_index("bucket", "docs/", "bm25_index/index.json")

        self.assertEqual(num, 1)
        uploaded = json.loads(client.upload_fileobj.call_args[0][0].read().decode("utf-8"))
        self.assertEqual(uploaded["chunk_metadata"][0], self._CANONICAL_FAQ_METADATA)

    def test_semantic_header_is_byte_identical_to_pre_700_enriched_header(self):
        from etl.bm25_index_builder import _semantic_header

        question = "Wann kann ich in Rente gehen?"
        body = f"# {question}\n\nAntwort text."
        legacy_enriched = _legacy_enrich_faq_metadata(
            {
                "name": "FAQ Rentenbeginn",
                "brochure_number": "faq-a-und-b",
                "brochure_url": "https://drv.de/faq-a-und-b.html#content-1",
            },
            body,
        )
        self.assertEqual(
            _semantic_header(self._CANONICAL_FAQ_METADATA),
            _semantic_header(legacy_enriched),
        )


if __name__ == "__main__":
    unittest.main()
