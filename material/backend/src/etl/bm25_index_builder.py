"""BM25 index builder Lambda handler.

Triggered by S3 ObjectCreated/Removed events via SQS whenever docs/*.md chunks
change. Also supports direct operator invocation. CloudFormation Delete events
return immediately (compatibility guard for the removed custom resource).
"""

import json
import logging
import os
from io import BytesIO

import boto3
from botocore.exceptions import ClientError

from bm25_shared.frontmatter import strip_frontmatter
from bm25_shared.retrieval_manifest import RetrievalManifest
from bm25_shared.tokenizer import TOKENIZER_REVISION, tokenize

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def list_chunk_keys(client, bucket, prefix):
    """List all .md chunk keys under an S3 prefix."""
    keys = []
    continuation_token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        resp = client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".md") and ".metadata.json" not in key:
                keys.append(key)
        if not resp.get("IsTruncated"):
            break
        continuation_token = resp["NextContinuationToken"]
    return keys


def _load_chunk_metadata(client, bucket, key):
    """Load chunk sidecar metadata if present."""
    try:
        resp = client.get_object(Bucket=bucket, Key=f"{key}.metadata.json")
        return json.loads(resp["Body"].read()).get("metadataAttributes", {})
    except Exception:
        return {}


def _semantic_header(metadata):
    """Build a searchable document-path header for BM25 without changing returned content."""
    # Only include keywords/synonyms for LLM-enriched chunks; DITA keywords stay out of the header.
    is_enriched = metadata.get("enriched", False)
    enriched_keywords = metadata.get("keywords") if is_enriched else None
    fields = [
        ("Dokument", metadata.get("title") or metadata.get("name") or metadata.get("source_name")),
        ("Broschüre", metadata.get("brochure_number")),
        ("Kategorie", metadata.get("category")),
        ("Abschnitt", metadata.get("section_title")),
        ("Unterabschnitt", metadata.get("subsection_title")),
        ("Schlüsselwörter", enriched_keywords),
        ("Synonyme", metadata.get("colloquial_terms") if is_enriched else None),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value]
    if not lines:
        return ""
    semantic_path = " > ".join(str(value) for _, value in fields if value)
    lines.append(f"Suchpfad: {semantic_path}")
    return "\n".join(lines)


def build_index(
    bucket,
    prefix,
    index_key,
    *,
    release_id="legacy",
    retrieval_artifact_id=None,
    tokenizer_revision=TOKENIZER_REVISION,
    chunk_id_base_prefix="",
):
    """Build BM25 index from S3 chunks and upload as JSON.

    Returns the number of indexed chunks.
    """
    client = boto3.client("s3")

    chunk_keys = list_chunk_keys(client, bucket, prefix)
    if not chunk_keys:
        logger.warning("No chunks found, skipping BM25 index build")
        return 0

    logger.info(f"Building BM25 index from {len(chunk_keys)} chunks")

    chunk_ids = []
    chunk_contents = []
    chunk_metadata = []
    corpus = []

    for key in chunk_keys:
        resp = client.get_object(Bucket=bucket, Key=key)
        raw = resp["Body"].read().decode("utf-8")
        text = strip_frontmatter(raw)
        metadata = _load_chunk_metadata(client, bucket, key)
        indexed_text = f"{_semantic_header(metadata)}\n\n{text}" if metadata else text
        tokens = tokenize(indexed_text)
        if not tokens:
            continue
        chunk_ids.append(key.removeprefix(chunk_id_base_prefix))
        chunk_contents.append(text)
        chunk_metadata.append(metadata)
        corpus.append(tokens)

    if not corpus:
        logger.warning("No tokenizable chunks")
        return 0

    index_data = {
        "schema_version": 2 if retrieval_artifact_id else 1,
        "release_id": release_id,
        "bm25_tokenizer_revision": tokenizer_revision,
        "corpus": corpus,
        "chunk_ids": chunk_ids,
        "chunk_contents": chunk_contents,
        "chunk_metadata": chunk_metadata,
    }
    if retrieval_artifact_id:
        index_data["retrieval_artifact_id"] = retrieval_artifact_id

    encoded_index = json.dumps(index_data, ensure_ascii=False).encode("utf-8")
    if release_id == "legacy":
        client.upload_fileobj(BytesIO(encoded_index), bucket, index_key)
    else:
        # Release key is content-addressed and write-once; IfNoneMatch makes immutability atomic.
        try:
            client.put_object(
                Bucket=bucket,
                Key=index_key,
                Body=encoded_index,
                ContentType="application/json",
                IfNoneMatch="*",
                ChecksumAlgorithm="SHA256",
                Tagging="renate%3Aretention=pinned",
            )
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code not in {"PreconditionFailed", "412"} and status != 412:
                raise

            # Retried promotion can reach the same key; byte-identical content is success, any collision fails closed.
            existing = client.get_object(Bucket=bucket, Key=index_key)["Body"].read()
            if existing != encoded_index:
                raise ValueError(f"immutable BM25 index already differs: s3://{bucket}/{index_key}") from error
            logger.info(
                "Immutable BM25 index already exists with identical bytes: s3://%s/%s",
                bucket,
                index_key,
            )
    logger.info(f"BM25 index uploaded: s3://{bucket}/{index_key} ({len(chunk_ids)} chunks)")
    return len(chunk_ids)


def _validate_manifest_for_builder(manifest: RetrievalManifest, bucket: str) -> None:
    expected_coordinates = {
        "knowledge_base_id": os.environ.get("RETRIEVAL_KNOWLEDGE_BASE_ID"),
        "data_source_id": os.environ.get("RETRIEVAL_DATA_SOURCE_ID"),
    }
    if manifest.bm25_bucket != bucket:
        raise ValueError(
            f"retrieval manifest bm25_bucket {manifest.bm25_bucket!r} does not match builder bucket {bucket!r}"
        )
    if manifest.bm25_tokenizer_revision != TOKENIZER_REVISION:
        raise ValueError(
            "retrieval manifest tokenizer revision "
            f"{manifest.bm25_tokenizer_revision!r} is incompatible with builder revision {TOKENIZER_REVISION!r}"
        )
    for field, expected in expected_coordinates.items():
        if expected and getattr(manifest, field) != expected:
            raise ValueError(
                f"retrieval manifest {field} {getattr(manifest, field)!r} does not match builder coordinate {expected!r}"
            )


def handler(event, context):
    """Route SQS, direct operator invocations, and the one-time CFN Delete guard."""
    if event.get("RequestType") == "Delete":
        logger.info("CFN Delete event received — returning no-op for custom resource removal")
        return

    bucket = os.environ["BM25_BUCKET"]
    prefix = os.environ.get("BM25_CHUNK_PREFIX", "docs/")
    index_key = os.environ.get("BM25_INDEX_KEY", "bm25_index/index.json")
    release_id = "legacy"
    retrieval_artifact_id = None

    manifest_payload = event.get("retrieval_manifest")
    if manifest_payload is not None:
        manifest = RetrievalManifest.from_dict(manifest_payload)
        _validate_manifest_for_builder(manifest, bucket)
        index_key = manifest.bm25_key
        release_id = manifest.release_id
        retrieval_artifact_id = manifest.retrieval_artifact_id
        prefix = f"{manifest.processed_prefix}docs/"
    elif os.environ.get("BM25_IMMUTABLE_ONLY", "false").lower() == "true":
        logger.info("Skipping green BM25 event: immutable release builds require retrieval_manifest")
        return {"Skipped": "retrieval_manifest required"}

    logger.info(f"Rebuilding BM25 index: s3://{bucket}/{prefix}")
    if manifest_payload is None:
        num_chunks = build_index(bucket, prefix, index_key)
    else:
        num_chunks = build_index(
            bucket,
            prefix,
            index_key,
            release_id=release_id,
            retrieval_artifact_id=retrieval_artifact_id,
            tokenizer_revision=TOKENIZER_REVISION,
            chunk_id_base_prefix=manifest.processed_prefix,
        )
    logger.info(f"BM25 index rebuilt with {num_chunks} chunks")
    if manifest_payload is None:
        return {"NumChunks": num_chunks}
    return {
        "NumChunks": num_chunks,
        "ReleaseId": release_id,
        "RetrievalArtifactId": retrieval_artifact_id or release_id,
        "Bm25Key": index_key,
        "Bm25TokenizerRevision": TOKENIZER_REVISION,
    }
