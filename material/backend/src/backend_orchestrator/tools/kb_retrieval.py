"""Knowledge base retrieval with hybrid BM25 + semantic search."""

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urlparse

import boto3
from aws_lambda_powertools import Logger, Tracer
from opentelemetry import trace

from backend_orchestrator.config import get_config
from backend_orchestrator.observability import set_content_attribute
from backend_orchestrator.retrieval_manifest import snapshot_retrieval_config
from backend_orchestrator.tools.bm25_search import bm25_search, get_cached_chunk_metadata
from backend_orchestrator.tools.hyde import generate_hypothetical_document
from backend_orchestrator.utils.uri_utils import get_display_name
from bm25_shared.frontmatter import strip_frontmatter

logger = Logger(child=True)
tracer = Tracer()


def _get_otel_tracer():
    return trace.get_tracer(__name__)


@dataclass
class AgentDeps:
    """Dependencies injected into each agent run via RunContext."""

    sources: list[dict] = field(default_factory=list)
    kb_call_count: int = 0
    # Raw user question, used as a second retrieval query and for year-match boosting
    # (the rephrased query routinely drops the birth year).
    original_question: str = ""
    last_retrieval_query: str = ""


_bedrock_client = None
_s3_client = None
_priority_map: dict | None = None

_RRF_K = 60

_TIER_WEIGHTS = {"S": 1.8, "E": 1.4, "A": 1.0, "UNKNOWN": 0.8}

_DOMAIN_WEIGHTS = {
    "rente": 1.2,
    "reha": 1.1,
    "versicherung": 1.1,
    "sonstiges": 1.0,
    "themenfremd": 0.1,
    "mehrdeutig": 0.9,
}

# Demote (not drop) cross-domain chunks so a strong lexical hit survives a domain misclassification.
_CROSS_DOMAIN_PENALTY = 0.3

# Hyphen-free; the query is normalized the same way so "I-RENA" and "IRENA" both match.
_RARE_TERMS = {
    "trena",
    "irena",
    "psyrena",
    "sucht",
    "knappschaft",
    "flexirente",
    "grundsicherung",
    "riester",
    "rürup",
    "betriebsrente",
}
# Anchored at a word start to avoid "untersucht"/"gesucht"/"besucht" matching the rare term "sucht".
_RARE_TERM_RE = re.compile(r"\b(?:" + "|".join(sorted(_RARE_TERMS)) + r")")

# Re-order precise per-cohort chunks above generic overview chunks on birth-year queries.
_YEAR_MATCH_BOOST = 1.5
_QUERY_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Expand only two-digit numbers adjacent to a birth keyword, so "mit 63 in Rente" isn't treated as a year.
_TWO_DIGIT_BIRTH_RE = re.compile(
    r"\b(?:jahrgang|baujahr|geboren)\s+(\d{2})\b|\b(\d{2})\s+geboren\b",
    re.IGNORECASE,
)

# Word-boundary splitter for both query/keyword matching and standalone-query gating.
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Rephrase stays primary; the raw question is weighted below to rescue docs the rephrase lost.
_ORIGINAL_QUERY_WEIGHT = 0.7

_STANDALONE_MIN_WORD_LEN = 4

# Function-only questions ("und dabei?") are meaningless without chat history, which retrieval doesn't have.
_FUNCTION_WORD_TEXT = (
    # pronouns / possessives / indefinites
    "ich du er sie es wir ihr mich mir dich dir ihn ihm uns euch ihnen mein meine meinen meinem "
    "meiner sein seine man wer wem wen "
    # demonstratives and pronominal adverbs — the actual follow-up back-references
    "der die das den dem des dies diese dieser dieses diesen dabei davon dafuer dafür damit "
    "danach daraus darin darauf dazu dort da hier so "
    # question words, auxiliaries, modals
    "was wie wo wann warum welche welcher welches ob ist sind war waren bin bist hat habe haben "
    "hatte wird werde werden wurde kann koennen können darf duerfen dürfen muss muessen müssen "
    "soll sollen will wollen gibt "
    # prepositions, conjunctions, particles
    "und oder aber denn auch noch nur schon dann wenn als mit ohne in im an am auf aus bei beim "
    "fuer für von vom vor nach zu zum zur ueber über unter um bis ab nicht kein keine ein eine "
    "einen einem einer eines etwa bitte danke ja nein"
)
_FUNCTION_WORDS = frozenset(_FUNCTION_WORD_TEXT.split())


class Domain(StrEnum):
    """DRV question domains; lowercase German for unambiguous model output."""

    RENTE = "rente"
    REHA = "reha"
    VERSICHERUNG = "versicherung"
    SONSTIGES = "sonstiges"
    THEMENFREMD = "themenfremd"
    MEHRDEUTIG = "mehrdeutig"


def _get_bedrock_client(region: str):
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-agent-runtime", region_name=region)
    return _bedrock_client


def _rerank_results(client, query: str, results: list[dict], model_arn: str, top_n: int) -> list[dict]:
    """Rerank retrieval results using the Bedrock rerank API."""
    with _get_otel_tracer().start_as_current_span("retrieval.rerank") as span:
        span.set_attribute("retrieval.rerank.model_arn", model_arn)
        span.set_attribute("retrieval.rerank.input_count", len(results))
        span.set_attribute("retrieval.rerank.top_n", top_n)
        try:
            response = client.rerank(
                rerankingConfiguration={
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "modelConfiguration": {"modelArn": model_arn},
                        "numberOfResults": min(top_n, len(results)),
                    },
                },
                sources=[
                    {
                        "type": "INLINE",
                        "inlineDocumentSource": {
                            "type": "TEXT",
                            "textDocument": {"text": r.get("content", "")},
                        },
                    }
                    for r in results
                ],
                queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            )
            reranked = response.get("results", [])
            reranked_results = [results[r["index"]] for r in reranked if r["index"] < len(results)]
            scores = [(r["index"], round(r.get("relevanceScore", 0), 4)) for r in reranked]
            if not reranked_results and results:
                logger.warning(
                    "Reranking returned no usable results, falling back to original order",
                    extra={"original_count": len(results), "top_n": top_n},
                )
                reranked_results = results[:top_n]
            span.set_attribute("retrieval.rerank.output_count", len(reranked_results))
            logger.info(
                "Reranking complete",
                extra={"original": len(results), "reranked": len(reranked_results), "scores": scores},
            )
        except Exception:
            logger.exception("Reranking failed, falling back to original order")
            span.set_attribute("retrieval.rerank.error", "fallback")
            reranked_results = results[:top_n]
        return reranked_results


def _get_s3_client(region: str):
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client


def _s3_key_from_uri(uri: str) -> str:
    parsed = urlparse(uri)
    return parsed.path.lstrip("/")


def _semantic_search(
    query: str, config, brochure_filter: str | None = None, num_results: int | None = None
) -> list[dict]:
    """Run semantic search via Bedrock Knowledge Base.

    ``brochure_filter`` scopes a supplementary call whose hits are unioned into the pool; it
    doesn't narrow the main pipeline. Returns dicts with s3_key, content, metadata, source_uri, score.
    """
    kb_id = config.knowledge_base_id
    region = config.aws_region
    release_id = getattr(config, "retrieval_release_id", "legacy-environment")
    num_results = num_results or config.kb_retrieval_results

    if not kb_id:
        logger.warning("KNOWLEDGE_BASE_ID not configured")
        return []

    client = _get_bedrock_client(region)

    with _get_otel_tracer().start_as_current_span("retrieval.semantic") as span:
        span.set_attribute("retrieval.knowledge_base_id", kb_id)
        span.set_attribute("retrieval.release_id", release_id)
        set_content_attribute(span, "retrieval.query", query[:200])
        span.set_attribute("retrieval.num_results_requested", num_results)
        if brochure_filter:
            span.set_attribute("retrieval.brochure_filter", brochure_filter)

        vector_config: dict = {"numberOfResults": num_results, "overrideSearchType": "SEMANTIC"}
        if brochure_filter:
            vector_config["filter"] = {"equals": {"key": "brochure_number", "value": brochure_filter}}

        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={"vectorSearchConfiguration": vector_config},
        )

        results = []
        for result in response.get("retrievalResults", []):
            metadata = result.get("metadata", {})
            source_uri = metadata.get("x-amz-bedrock-kb-source-uri")
            if not source_uri:
                location = result.get("location", {})
                s3_location = location.get("s3Location", {})
                source_uri = s3_location.get("uri")

            content = result.get("content", {}).get("text", "")
            content = strip_frontmatter(content)

            s3_key = _s3_key_from_uri(source_uri) if source_uri else ""

            results.append({
                "s3_key": s3_key,
                "content": content,
                "metadata": metadata,
                "source_uri": source_uri or "Unknown source",
                "score": result.get("score", 0),
                "release_id": release_id,
            })

        span.set_attribute("retrieval.num_results_returned", len(results))

    return results


def _fetch_s3_metadata_sidecar(s3_key: str, bucket: str, config) -> dict:
    """Fetch metadata sidecar (.metadata.json) for a document from S3."""
    try:
        client = _get_s3_client(config.aws_region)
        meta_key = f"{s3_key}.metadata.json"
        resp = client.get_object(Bucket=bucket, Key=meta_key)
        sidecar = json.loads(resp["Body"].read())
        return sidecar.get("metadataAttributes", {})
    except Exception as exc:
        # WARNING, not DEBUG: AccessDenied silently strips citation title/date/boost; keep alarmable.
        logger.warning(
            "Metadata sidecar unavailable",
            extra={"s3_key": s3_key[:120], "bucket": bucket, "error": type(exc).__name__},
        )
        return {}


def _fetch_bm25_metadata(s3_key: str, config) -> dict:
    """Fetch metadata sidecar for a BM25-only hit from S3."""
    return _fetch_s3_metadata_sidecar(s3_key, config.bm25_index_bucket, config)


def _rrf_fusion(semantic_results: list[dict], bm25_results: list[dict], bm25_weight: float) -> list[dict]:
    """Fuse semantic and BM25 results via Reciprocal Rank Fusion."""
    merged: dict[str, dict] = {}

    for rank, result in enumerate(semantic_results, 1):
        key = result.get("s3_key")
        if not key:
            base = result.get("source_uri") or ""
            key = f"semantic_unkeyed:{base}:{rank}"
        rrf_score = 1.0 / (rank + _RRF_K)
        merged[key] = {
            **result,
            "s3_key": key,
            "rrf_score": rrf_score,
            "sources": {"semantic"},
        }

    for rank, result in enumerate(bm25_results, 1):
        key = result["chunk_id"]
        rrf_score = bm25_weight / (rank + _RRF_K)

        if key in merged:
            merged[key]["rrf_score"] += rrf_score
            merged[key]["sources"].add("bm25")
            # Immutable releases can't fall back to the mutable sidecar; semantic wins, release fills gaps.
            embedded = result.get("metadata") or {}
            if embedded:
                metadata = merged[key].get("metadata") or {}
                for meta_key, value in embedded.items():
                    metadata.setdefault(meta_key, value)
                merged[key]["metadata"] = metadata
        else:
            merged[key] = {
                "s3_key": key,
                "content": result["content"],
                "metadata": result.get("metadata", {}),
                "source_uri": "",
                "rrf_score": rrf_score,
                "sources": {"bm25"},
                "release_id": result.get("release_id"),
            }

    return sorted(merged.values(), key=lambda x: x["rrf_score"], reverse=True)


def _standalone_query(original_question: str, rephrased_query: str) -> str:
    """Return the raw user question when it's a usable second retrieval query, else "".

    Rejects (a) pure back-references with no content word and (b) queries that duplicate the rephrase.
    """
    raw = (original_question or "").strip()
    if not raw:
        return ""
    raw_tokens = set(_WORD_RE.findall(raw.lower()))
    content = {
        t for t in raw_tokens if t not in _FUNCTION_WORDS and len(t) >= _STANDALONE_MIN_WORD_LEN and not t.isdigit()
    }
    if not content:
        return ""
    if raw_tokens == set(_WORD_RE.findall((rephrased_query or "").lower())):
        return ""
    return raw


def _fuse_query_variants(
    primary: list[dict], secondary: list[dict], key_field: str, secondary_weight: float
) -> list[dict]:
    """Reorder two ranked result lists from one retriever by weighted RRF; shape unchanged.

    Fuses queries (not retrievers): downstream stages consume by position, so order is the payload.
    """
    fused: dict[str, dict] = {}
    for weight, results in ((1.0, primary), (secondary_weight, secondary)):
        for rank, result in enumerate(results, 1):
            key = result.get(key_field) or f"unkeyed:{id(result)}"
            entry = fused.get(key)
            if entry is None:
                fused[key] = {"result": result, "score": weight / (rank + _RRF_K)}
            else:
                entry["score"] += weight / (rank + _RRF_K)
    ordered = sorted(fused.values(), key=lambda e: e["score"], reverse=True)
    return [e["result"] for e in ordered]


def _semantic_search_variants(retrieval_query: str, second_query: str, config) -> list[dict]:
    """Retrieve with the primary query, fuse the raw question when usable, truncate to budget."""
    primary = _semantic_search(retrieval_query, config)
    if not second_query:
        return primary
    secondary = _semantic_search(second_query, config)
    fused = _fuse_query_variants(primary, secondary, "s3_key", _ORIGINAL_QUERY_WEIGHT)
    return fused[: config.kb_retrieval_results]


def _bm25_search_variants(query: str, second_query: str, config) -> list[dict]:
    """Lexical counterpart of _semantic_search_variants. Index is already loaded, no network call."""
    primary = bm25_search(query, top_k=config.kb_retrieval_results, retrieval_snapshot=config)
    if not second_query:
        return primary
    secondary = bm25_search(second_query, top_k=config.kb_retrieval_results, retrieval_snapshot=config)
    fused = _fuse_query_variants(primary, secondary, "chunk_id", _ORIGINAL_QUERY_WEIGHT)
    return fused[: config.kb_retrieval_results]


def _load_priority_map() -> dict:
    """Load brochure priority map; keys are brochure numbers (e.g. 'B01')."""
    try:
        with open(get_config().brochure_priority_file, encoding="utf-8") as f:
            entries = json.load(f)
        pm: dict = {
            e["name"].strip(): {
                "prio": e["prio"],
                "domain": e.get("domain", ""),
                "authority_boost": e["authority_boost"],
            }
            for e in entries
            if e.get("name")
        }
    except Exception as ex:
        logger.warning("Could not load brochure priorities", extra={"error": str(ex)})
        return {}
    else:
        return pm


def _get_priority_map() -> dict:
    global _priority_map
    if _priority_map is None:
        _priority_map = _load_priority_map()
    return _priority_map


_BROCHURE_KEY_RE = re.compile(r"^((?:ALT-)?[A-Z]{1,4}\d+)")


def _extract_brochure_number(s3_key: str) -> str:
    """Extract brochure number from the chunk's parent folder (e.g. 'docs/B02_Name/chunk.md' → 'B02').

    Returns "" for folders that don't start with a brochure code; the brochure_number metadata
    field is authoritative in that case.
    """
    parts = s3_key.split("/")
    basename = parts[-2] if len(parts) >= 2 else s3_key
    # Normalize ALT_B* → ALT-B* to match priority map keys.
    basename = re.sub(r"^ALT_([A-Z])", r"ALT-\1", basename)
    m = _BROCHURE_KEY_RE.match(basename)
    return m.group(1) if m else ""


def _lookup_brochure(pm: dict, brochure_number: str, s3_key: str = "") -> dict | None:
    """Look up brochure by brochure_number metadata field, falling back to s3_key prefix."""
    key = (brochure_number or "").strip() or _extract_brochure_number(s3_key)
    result = pm.get(key) if key else None
    logger.debug("Brochure lookup", extra={"key": key, "s3_key": s3_key[:60], "found": result is not None})
    return result


def _prefetch_metadata(results: list[dict], config) -> None:
    """Populate metadata in-place before authority boost.

    Resolution order: existing metadata → in-memory release-pinned BM25 index → mutable docs/
    sidecar (legacy only — an immutable release must not be described by a newer object).
    """
    for r in results:
        s3_key = r.get("s3_key", "")
        if not s3_key:
            continue
        metadata = r.get("metadata") or {}
        if metadata.get("brochure_number"):
            continue

        embedded = get_cached_chunk_metadata(s3_key, config)
        for key, value in embedded.items():
            metadata.setdefault(key, value)

        includes_bm25 = "bm25" in (r.get("sources") or set())
        immutable_bm25 = includes_bm25 and getattr(config, "retrieval_legacy_fallback", True) is False
        if not metadata.get("brochure_number") and not immutable_bm25 and config.bm25_index_bucket:
            sidecar = _fetch_s3_metadata_sidecar(s3_key, config.bm25_index_bucket, config)
            for key, value in sidecar.items():
                metadata.setdefault(key, value)
        r["metadata"] = metadata


def _apply_authority_boost(results: list[dict], domain: str | None = None) -> list[dict]:
    """Apply authority boost to retrieval results, with domain-specific tier weighting."""
    pm = _get_priority_map()
    hits, misses = 0, 0
    for r in results:
        brochure_number = r.get("metadata", {}).get("brochure_number", "")
        if not brochure_number:
            logger.error(
                "Chunk missing brochure_number metadata — authority boost unavailable",
                extra={"s3_key": r.get("s3_key", "")[:80]},
            )
        data = _lookup_brochure(pm, brochure_number, r.get("s3_key", ""))
        if data:
            hits += 1
            base_boost = data["authority_boost"]
            tier = (data.get("prio") or "").strip().upper()[:1]
            data_domain = data.get("domain", "").lower()
            # Tier weight only when brochure belongs to the queried domain
            weight = (
                _TIER_WEIGHTS.get(tier, _TIER_WEIGHTS["UNKNOWN"]) if (not domain or data_domain == str(domain)) else 1.0
            )
            boost = base_boost * weight
            prio = data.get("prio", "UNKNOWN")
            domain_tier = tier if data_domain == str(domain) else None
        else:
            misses += 1
            boost, prio, domain_tier = 1.0, "UNKNOWN", None

        # Prefer the anchor stage's rank-fusion score when present: it is the only value on the
        # anchor path that is comparable across retrievers. Falls back to the fused ``rrf_score``
        # (non-anchor path) and finally to the raw semantic score.
        orig = r.get("anchor_score", r.get("rrf_score", r.get("score", 0)))
        r["rrf_score"] = orig * boost
        r["authority_boost"] = boost
        r["priority_level"] = prio
        r["original_score"] = r.get("original_score", orig)
        if domain and domain_tier:
            r["domain_tier"] = domain_tier
            r["domain"] = domain

    logger.info("Authority boost applied", extra={"hits": hits, "misses": misses, "domain": domain})
    results.sort(key=lambda x: x.get("rrf_score", 0), reverse=True)
    return results


def _filter_by_domain(results: list[dict], domain: str | None) -> list[dict]:
    """Demote (don't drop) chunks whose brochure belongs to a different specific domain.

    Keeps strong lexical hits alive through a domain misclassification; re-sorts by adjusted score.
    """
    if not domain or domain in (Domain.MEHRDEUTIG, Domain.THEMENFREMD, Domain.SONSTIGES):
        return results
    pm = _get_priority_map()
    penalized = 0
    for r in results:
        data = _lookup_brochure(pm, r.get("metadata", {}).get("brochure_number", ""), r.get("s3_key", ""))
        brochure_domain = (data or {}).get("domain", "").lower()
        in_domain = not brochure_domain or brochure_domain == str(domain) or brochure_domain == Domain.MEHRDEUTIG
        if not in_domain:
            r["rrf_score"] = r.get("rrf_score", r.get("score", 0)) * _CROSS_DOMAIN_PENALTY
            r["cross_domain_penalized"] = True
            penalized += 1
    results.sort(key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)
    logger.info("Domain demotion applied", extra={"domain": domain, "penalized": penalized, "kept": len(results)})
    return results


def _extract_query_years(text: str) -> set[str]:
    """Return 4-digit years implied by the text; expands "Jahrgang 63"/"63 geboren" to 19YY."""
    years = set(_QUERY_YEAR_RE.findall(text))
    for groups in _TWO_DIGIT_BIRTH_RE.findall(text):
        yy = next(g for g in groups if g)
        years.add(str(1900 + int(yy)))
    return years


def _apply_year_match_boost(results: list[dict], *query_texts: str) -> list[dict]:
    """Boost chunks containing a year named in any query_texts, then re-sort by score.

    Pass both the rephrased query AND the original question — the rephrase drops birth years.
    No-op when no text names a year.
    """
    years: set[str] = set()
    for text in query_texts:
        years |= _extract_query_years(text)
    if not years:
        return results
    # Whole-token match so "1963" doesn't hit inside "11963".
    year_re = re.compile(r"\b(?:" + "|".join(sorted(years)) + r")\b")
    boosted = 0
    for r in results:
        if year_re.search(r.get("content", "")):
            r["rrf_score"] = r.get("rrf_score", r.get("score", 0)) * _YEAR_MATCH_BOOST
            r["year_match_boosted"] = True
            boosted += 1
    results.sort(key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)
    logger.info("Year-match boost applied", extra={"years": sorted(years), "boosted": boosted, "kept": len(results)})
    return results


# --- Anchor retrieval (inlined from anchor_retrieval.py) ---


# Canonical document-identity patterns. These mirror the ETL naming convention documented in
# etl.util.repository.s3.S3BucketRepository.list_by_stem, applied in reverse. Compiled once at
# module level because _doc_key runs per candidate chunk on the retrieval hot path.
_LEGACY_CHUNK_SUFFIX_RE = re.compile(r"(?:_chunk_\d+|\.chunk\.\d+).*$")
_TRAILING_CHUNK_INDEX_RE = re.compile(r"_\d{4}$")
_SUBDOC_INFIX_RE = re.compile(r"_(?:note|table)_\d{3,}$")
# Known content extensions the ETL transform emits; stripped from a flat/single-file basename
# before the trailing chunk index in the folder-first fallback branch.
_KNOWN_EXTENSION_RE = re.compile(r"\.(?:md|pdf|html|xml|json)$", re.IGNORECASE)
# A bare legacy chunk filename ("chunk_0000.md") carries no document identity of its own — its
# parent folder is the document. Same rule utils.uri_utils.get_display_name already applies.
_BARE_CHUNK_FILE_RE = re.compile(r"^chunk[._]\d+", re.IGNORECASE)


def _key_to_path(s3_key: str, source_uri: str) -> str:
    """Reduce an S3 key or ``s3://`` URI to a leading-slash-free object path."""
    raw = s3_key or source_uri or ""
    if "://" in raw:
        raw = urlparse(raw).path
    return raw.lstrip("/")


def _doc_key(s3_key: str, source_uri: str) -> str:
    """Canonical LOGICAL document identity for anchor grouping.

    Folder-first and prefix-invariant. Production chunks are ``docs/<stem>/<stem>_NNNN.md``, so
    the chunk's folder is the document stem regardless of any leading prefix (``docs/`` or an
    immutable ``releases/<v>/processed/docs/`` path) — the semantic and BM25 copies of one chunk
    therefore resolve to the same stem. ``_note_NNN``/``_table_NNN`` sub-documents fold into
    their parent source document, and legacy ``<folder>/chunk_NNNN`` or flat ``<stem>_chunk_<n>``
    keys still resolve to their stem. Drop-in replacement: same signature and single call site
    (``_apply_anchor_retrieval``); returns ``"unknown_document"`` when there is no key at all.
    """
    path = _key_to_path(s3_key, source_uri)
    if not path:
        return "unknown_document"
    # Legacy: flat "<stem>_chunk_<n>" / "<stem>.chunk.<n>" suffix anywhere in the path.
    path = _LEGACY_CHUNK_SUFFIX_RE.sub("", path)
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "unknown_document"

    basename = parts[-1]
    if len(parts) >= 2 and (basename.startswith(parts[-2]) or _BARE_CHUNK_FILE_RE.match(basename)):
        # Folder-nested chunk: the folder (parts[-2]) is the document stem, prefix-invariant.
        stem = parts[-2]
    else:
        # Flat / single-file / legacy key: drop the known extension then the trailing _NNNN index.
        stem = _TRAILING_CHUNK_INDEX_RE.sub("", _KNOWN_EXTENSION_RE.sub("", basename))

    # Fold focused note/table sub-documents into their parent source document.
    stem = _SUBDOC_INFIX_RE.sub("", stem)
    return stem or "unknown_document"


def _physical_chunk_id(s3_key: str, source_uri: str) -> str:
    """Prefix-invariant ``<folder>/<file>`` identity for one physical chunk.

    De-duplicates the semantic (``releases/<v>/processed/docs/…``) and BM25 (``docs/…``) copies
    of the same physical chunk inside a document group without touching ``_rrf_fusion``.
    """
    path = _LEGACY_CHUNK_SUFFIX_RE.sub("", _key_to_path(s3_key, source_uri))
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "unknown_chunk"
    return "/".join(parts[-2:])


def _dedup_group_by_physical_chunk(chunks: list[dict]) -> list[dict]:
    """Collapse the semantic and BM25 copies of one physical chunk within a group.

    Keeps the higher-scoring copy (the one Stage 2 would pick anyway) so a single physical
    chunk is neither scored nor emitted twice. The group count is unaffected.
    """
    deduped: dict[str, dict] = {}
    for c in chunks:
        pid = _physical_chunk_id(c.get("s3_key", ""), c.get("source_uri", ""))
        existing = deduped.get(pid)
        if existing is None or c.get("rrf_score", c.get("score", 0)) > existing.get(
            "rrf_score", existing.get("score", 0)
        ):
            deduped[pid] = c
    return list(deduped.values())


def _is_rare_term_query(query: str) -> bool:
    """Return True if the query mentions a rare DRV term that warrants an anchor boost.

    Hyphens are stripped before matching so every spelling of the Reha-Nachsorge acronyms
    ("IRENA", "I-RENA", "T-RENA", "Psy-RENA") is caught. Matching is anchored to a word start
    (see ``_RARE_TERM_RE``) so a term like "sucht" hits "Sucht"/"Suchtberatung" but not the
    everyday suffix forms "untersucht"/"gesucht"/"besucht", which a plain substring check
    wrongly flagged as rare-term queries.
    """
    normalized = query.lower().replace("-", "")
    return _RARE_TERM_RE.search(normalized) is not None


def _anchor_fusion_scores(
    semantic_results: list[dict], bm25_results: list[dict], bm25_weight: float
) -> dict[str, float]:
    """Reciprocal-rank-fusion score per physical chunk, keyed by ``_physical_chunk_id``.

    The anchor stage receives the RAW semantic and BM25 result lists, whose scores are on
    incomparable scales: Bedrock returns a cosine similarity (~0.3-0.7) while BM25 returns an
    unbounded term-frequency score (~7-14 in this corpus). Comparing those directly made BM25
    top-k membership an effective *gate* on anchor selection — a document the vector search
    ranked well but BM25 missed entirely scored roughly an order of magnitude lower and could
    not win a slot, however high its tier or semantic rank.

    RRF reads only ranks, so it is immune to either retriever's score magnitude, and a chunk
    found by both retrievers accumulates both contributions. This mirrors ``_rrf_fusion``,
    which the non-anchor path already uses; the anchor path bypassed it and re-derived scores
    from the raw inputs.
    """
    scores: dict[str, float] = defaultdict(float)
    for rank, result in enumerate(semantic_results, 1):
        key = _physical_chunk_id(result.get("s3_key", ""), result.get("source_uri", ""))
        scores[key] += 1.0 / (rank + _RRF_K)
    for rank, result in enumerate(bm25_results, 1):
        key = _physical_chunk_id(result.get("chunk_id", ""), "")
        scores[key] += bm25_weight / (rank + _RRF_K)
    return scores


def _attach_anchor_scores(
    all_chunks: list[dict], semantic_results: list[dict], bm25_results: list[dict], config
) -> None:
    """Stamp every candidate chunk with its rank-fusion score, in place."""
    fusion = _anchor_fusion_scores(semantic_results, bm25_results, config.bm25_weight)
    for chunk in all_chunks:
        key = _physical_chunk_id(chunk.get("s3_key", ""), chunk.get("source_uri", ""))
        chunk["anchor_score"] = fusion.get(key, 0.0)


def _score_doc_for_anchor(
    best_chunk: dict, domain: str | None, pm: dict, domain_weight: float, rare_boost: float
) -> tuple[float, str]:
    """Return (score, tier) for a candidate anchor document.

    ``auth`` is 1.0 for every chunk here: authority boost is applied to the fused copies and to
    ``final_results`` AFTER selection, never to the raw lists this stage reads. The factor is
    kept so the formula still reflects intent, but it does not discriminate at selection time.
    """
    base = best_chunk.get("anchor_score", 0.0)
    auth = best_chunk.get("authority_boost", 1.0)
    brochure = _lookup_brochure(
        pm, best_chunk.get("metadata", {}).get("brochure_number", ""), best_chunk.get("s3_key", "")
    )
    if domain and brochure and brochure.get("domain", "").lower() == str(domain):
        tier = (brochure.get("prio") or "").strip().upper()[:1] or "UNKNOWN"
    else:
        prio = best_chunk.get("priority_level", "UNKNOWN")
        tier = prio[0] if prio and prio != "UNKNOWN" else "UNKNOWN"
    score = base * _TIER_WEIGHTS.get(tier, _TIER_WEIGHTS["UNKNOWN"]) * domain_weight * auth * rare_boost
    return score, tier


def _select_anchors(doc_scores: list[dict], s_tier_keys: list[str], config) -> list[str]:
    """Select anchor document keys: guarantee S-tier first, fill up to max."""
    selected: list[str] = []
    if config.anchor_s_tier_guaranteed:
        s_tier_sorted = sorted(
            (d for d in doc_scores if d["doc_key"] in s_tier_keys), key=lambda x: x["score"], reverse=True
        )
        selected = [d["doc_key"] for d in s_tier_sorted[:2]]
    for d in doc_scores:
        if len(selected) >= config.anchor_max_docs:
            break
        if d["doc_key"] not in selected:
            selected.append(d["doc_key"])
    while len(selected) < config.anchor_min_docs and len(selected) < len(doc_scores):
        for d in doc_scores:
            if d["doc_key"] not in selected:
                selected.append(d["doc_key"])
                break
    return selected


def _apply_anchor_retrieval(
    semantic_results: list[dict], bm25_results: list[dict], query: str, domain: str | None, config
) -> list[dict]:
    """2-stage anchor-first retrieval: select anchor documents, then pick best chunks.

    Formula: doc_score = (semantic + bm25) / 2 * tier_weight * domain_weight * authority_boost * rare_term_boost
    """
    bm25_conv = [
        {
            "s3_key": r["chunk_id"],
            "content": r["content"],
            # Carry the release-embedded metadata through. Dropping it here used
            # to strip the citation title, the publishing date and the authority
            # boost from every BM25 hit that survived anchor selection (#676) —
            # unrecoverably so in manifest mode, where the mutable sidecar must
            # not be consulted.
            "metadata": r.get("metadata") or {},
            "source_uri": "",
            "score": 0,
            "rrf_score": r.get("score", 0),
        }
        for r in bm25_results
    ]
    all_chunks = semantic_results + bm25_conv
    if not all_chunks:
        return []

    with _get_otel_tracer().start_as_current_span("retrieval.anchor") as span:
        # Put both retrievers on one rank-based scale before anything is compared or sorted.
        # Duplicate semantic/BM25 copies of one physical chunk share a score by construction,
        # so the physical de-dup below is unaffected and keeps choosing the same survivor.
        _attach_anchor_scores(all_chunks, semantic_results, bm25_results, config)

        doc_groups: dict[str, list[dict]] = defaultdict(list)
        for c in all_chunks:
            doc_groups[_doc_key(c.get("s3_key", ""), c.get("source_uri", ""))].append(c)

        # De-duplicate the semantic and BM25 copies of one physical chunk within each group so a
        # single chunk is neither scored nor emitted twice. Group count is unaffected.
        for dk, chunks in doc_groups.items():
            doc_groups[dk] = _dedup_group_by_physical_chunk(chunks)

        rare_boost = config.anchor_rare_term_boost if _is_rare_term_query(query) else 1.0
        domain_weight = _DOMAIN_WEIGHTS.get(domain, 1.0) if domain else 1.0
        pm = _get_priority_map()

        # Stage 1: score documents and select anchors
        doc_scores = []
        s_tier_keys = []
        for dk, chunks in doc_groups.items():
            best = max(chunks, key=lambda x: x.get("anchor_score", 0.0))
            score, tier = _score_doc_for_anchor(best, domain, pm, domain_weight, rare_boost)
            doc_scores.append({"doc_key": dk, "score": score, "tier": tier})
            if tier == "S":
                s_tier_keys.append(dk)

        doc_scores.sort(key=lambda x: x["score"], reverse=True)
        selected = _select_anchors(doc_scores, s_tier_keys, config)

        multi_chunk_groups = sum(1 for chunks in doc_groups.values() if len(chunks) > 1)
        singleton_groups = len(doc_groups) - multi_chunk_groups

        # Stage 2: pick best chunks from each anchor document
        max_chunks = config.kb_retrieval_results
        chunks_per = max(1, max_chunks // len(selected)) if selected else 1
        chunks_per_anchor: dict[str, int] = {}
        result: list[dict] = []
        for dk in selected:
            if dk not in doc_groups:
                continue
            top = sorted(doc_groups[dk], key=lambda x: x.get("anchor_score", 0.0), reverse=True)
            picked = top[: min(chunks_per, config.anchor_chunks_per_doc)]
            for c in picked:
                c["is_anchor"] = True
                c["anchor_document"] = dk
                result.append(c)
            chunks_per_anchor[dk] = len(picked)
            if len(result) >= max_chunks:
                break

        # Observability: a CloudWatch Logs metric filter alarms if logical_groups ever collapses
        # back toward input_chunks (the #699 regression signature — every chunk its own document).
        span.set_attribute("retrieval.anchor.input_chunks", len(all_chunks))
        span.set_attribute("retrieval.anchor.logical_groups", len(doc_groups))
        span.set_attribute("retrieval.anchor.multi_chunk_groups", multi_chunk_groups)
        span.set_attribute("retrieval.anchor.selected_anchors", len(selected))
        logger.info(
            "Anchor grouping",
            extra={
                "input_chunks": len(all_chunks),
                "logical_groups": len(doc_groups),
                "multi_chunk_groups": multi_chunk_groups,
                "singleton_groups": singleton_groups,
                "selected_anchors": len(selected),
                "chunks_per_anchor": chunks_per_anchor,
                "domain": domain,
            },
        )

        result.sort(key=lambda x: x.get("anchor_score", 0.0), reverse=True)
        return result[:max_chunks]


def _keyword_phrase_matches(query_tokens: set[str], keywords_csv: str) -> int:
    """Count curated keyword phrases (comma-separated) whose tokens are all present in the query."""
    if not keywords_csv:
        return 0
    matches = 0
    for phrase in keywords_csv.split(","):
        phrase_tokens = set(_WORD_RE.findall(phrase.lower()))
        # Require a multi-token phrase OR a specific single compound (len>=8, e.g.
        # "Kindererziehungszeiten") to avoid routing on a lone generic word like "Rente"/"Beitrag".
        if not phrase_tokens:
            continue
        specific = len(phrase_tokens) > 1 or any(len(t) >= 8 for t in phrase_tokens)
        if specific and phrase_tokens <= query_tokens:
            matches += 1
    return matches


def _route_target_brochure(results: list[dict], query: str, config) -> str | None:
    """Pick the one brochure whose curated primary_keywords most clearly match the query.

    Returns a ``brochure_number`` only when the curated metadata points somewhere specific: at least
    ``metadata_routing_min_matches`` keyword-phrase matches, and a top score shared by no more than
    ``metadata_routing_max_tied`` brochures. No-match and broadly-ambiguous queries return ``None``.

    Requiring *strictly* more matches than any other brochure abstained on every tie, which threw
    the routing pass away in exactly the situation it was built for. Observed in dev for "Kann ich
    mit 60 in Rente gehen?": B03 (Die richtige Altersrente) tied 1-1 on curated keywords, routing
    was suppressed, and the on-target brochure's own chunks were never pulled in — while B03's
    global similarity rank was too deep (43) to survive anchor selection on its own.

    Keyword matches and retrieval rank are independent signals, so a keyword tie is settled by
    retrieval evidence: among brochures on the top score, the one whose first chunk ranked highest
    wins. Setting ``metadata_routing_max_tied`` to 1 restores the strict rule.

    Breaking a tie the wrong way is cheap: routing only ever *unions* the target brochure's own
    chunks into the pool (see ``_merge_scoped_results``) and never replaces the all-brochure search,
    so the cost is a slice of retrieval budget rather than a wrong answer.
    """
    query_tokens = set(_WORD_RE.findall(query.lower()))
    scores: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for position, r in enumerate(results):
        meta = r.get("metadata") or {}
        bn = (meta.get("brochure_number") or "").strip()
        if not bn or bn in scores:
            continue
        scores[bn] = _keyword_phrase_matches(query_tokens, meta.get("primary_keywords", ""))
        first_seen[bn] = position
    if not scores:
        return None
    # Best keyword score first, then best retrieval position. Explicit rather than leaning on dict
    # insertion order surviving a stable sort, which made the tie-break invisible and fragile.
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
    top_bn, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    tied = sum(1 for _, score in ranked if score == top_score)
    if top_score >= config.metadata_routing_min_matches and tied <= config.metadata_routing_max_tied:
        logger.info(
            "Keyword routing target",
            extra={"brochure": top_bn, "score": top_score, "runner_up": runner_up, "tied": tied},
        )
        return top_bn
    logger.info(
        "Keyword routing: no clear target",
        extra={"top": top_bn, "top_score": top_score, "runner_up": runner_up, "tied": tied},
    )
    return None


def _merge_scoped_results(semantic_results: list[dict], scoped: list[dict]) -> list[dict]:
    """Union scoped (brochure-filtered) hits into the semantic pool, de-duplicating by s3_key."""
    seen = {r.get("s3_key", "") for r in semantic_results}
    added = [r for r in scoped if r.get("s3_key", "") and r.get("s3_key") not in seen]
    if added:
        logger.info("Keyword-routed scoped retrieval merged", extra={"added": len(added)})
    return semantic_results + added


def _validate_bm25_release(results: list[dict], config) -> None:
    """Reject lexical results that do not belong to the request snapshot."""
    expected = getattr(config, "retrieval_release_id", "legacy-environment")
    if not isinstance(expected, str):
        expected = "legacy-environment"
    legacy_fallback = getattr(config, "retrieval_legacy_fallback", True) is not False
    mismatched = [
        result.get("release_id")
        for result in results
        if result.get("release_id") != expected and not (legacy_fallback and result.get("release_id") is None)
    ]
    if mismatched:
        raise ValueError(f"BM25 results do not match request release {expected!r}: {mismatched!r}")


def _rank_scoped_results(scoped_results: list[dict]) -> None:
    """Put keyword-routed hits on the rank-fusion scale, in place.

    Scoped hits arrive as raw semantic results carrying a cosine ``score``. Every other path
    scores on the rank-fusion scale, which is more than an order of magnitude smaller, so
    without this the scoped pass would leapfrog the entire anchor set on units alone. Rank
    within the scoped call is the only ordering signal these hits carry anyway.
    """
    for rank, scoped in enumerate(scoped_results, 1):
        scoped["anchor_score"] = 1.0 / (rank + _RRF_K)


def _perform_search_and_enhancement(
    query: str, retrieval_query: str, config, domain: str | None, original_question: str = ""
) -> list[dict]:
    """Perform search and apply enhancements (authority boost, domain filter, anchor retrieval)."""
    # The rephrased query is primary; the raw question is a second opinion that can rescue a
    # document the rephrase lost (see _ORIGINAL_QUERY_WEIGHT). Empty when the raw text cannot
    # stand on its own or is just the rephrase again.
    second_query = _standalone_query(original_question, query)

    semantic_results = _semantic_search_variants(retrieval_query, second_query, config)
    logger.info(
        "Semantic search complete",
        extra={
            "num_results": len(semantic_results),
            "second_query": second_query[:50],
            "chunks": [r["s3_key"] for r in semantic_results],
        },
    )

    # Keyword-routed metadata retrieval: if the query unambiguously matches one brochure's curated
    # primary_keywords, pull that brochure's own deep chunks via a brochure-scoped retrieve. These
    # are injected AFTER anchor selection (below), because the global similarity ranking and the
    # anchor stage otherwise drop a low-similarity-but-correct answer chunk (e.g. the B26 "Nachzahlen
    # erlaubt" chunk for "rückwirkend freiwillige Beiträge") even though its brochure is the target.
    scoped_results: list[dict] = []
    if config.metadata_routing_enabled and semantic_results:
        try:
            target = _route_target_brochure(semantic_results, query, config)
            if target:
                scoped_results = _semantic_search(
                    retrieval_query, config, brochure_filter=target, num_results=config.metadata_routing_results
                )
        except Exception:
            logger.exception("Keyword-routed metadata retrieval failed, continuing with global results")

    bm25_results = []
    if config.bm25_enabled:
        try:
            loaded_bm25_results = _bm25_search_variants(query, second_query, config)
            _validate_bm25_release(loaded_bm25_results, config)
            bm25_results = loaded_bm25_results
            logger.info(
                "BM25 search complete",
                extra={
                    "num_results": len(bm25_results),
                    "chunks": [r["chunk_id"] for r in bm25_results],
                    "release_id": getattr(config, "retrieval_release_id", "legacy-environment"),
                },
            )
        except Exception:
            # #494: include retrieval_release_id so a CloudWatch Logs
            # MetricFilter can alarm on this — it fires for ANY BM25 failure
            # (bm25_search error or _validate_bm25_release's release-id
            # mismatch), which is exactly AC3's "vector/BM25 release_id
            # mismatch" detection. The mismatch detail itself, when this was
            # raised by _validate_bm25_release, is already in the exception
            # message that logger.exception attaches to the log record.
            # Runtime behavior is unchanged: still degrades to semantic-only.
            logger.exception(
                "BM25 search failed, using semantic-only",
                extra={"retrieval_release_id": getattr(config, "retrieval_release_id", "legacy-environment")},
            )

    if bm25_results:
        fused = _rrf_fusion(semantic_results, bm25_results, config.bm25_weight)
        intermediate_results = fused[: config.kb_retrieval_results]
    else:
        intermediate_results = [{**r, "rrf_score": 0, "sources": {"semantic"}} for r in semantic_results]

    _prefetch_metadata(intermediate_results, config)
    intermediate_results = _apply_authority_boost(intermediate_results, domain)
    intermediate_results = _filter_by_domain(intermediate_results, domain)
    logger.info("Authority boost + domain filter applied", extra={"chunks": len(intermediate_results)})

    if config.anchor_retrieval_enabled:
        try:
            final_results = _apply_anchor_retrieval(semantic_results, bm25_results, query, domain, config)
            _prefetch_metadata(final_results, config)
            final_results = _apply_authority_boost(final_results, domain)
            final_results = _filter_by_domain(final_results, domain)
            logger.info("Anchor retrieval applied", extra={"chunks": len(final_results)})
        except Exception as e:
            logger.warning("Anchor retrieval failed, using standard approach", extra={"error": str(e)})
            final_results = intermediate_results
    else:
        final_results = intermediate_results

    # Guarantee the keyword-routed brochure's own chunks reach the model: authority-boost the scoped
    # hits (their KB metadata already carries brochure_number, so no sidecar fetch is needed) — this
    # puts them on the same score X boost scale as the anchor-path results and earns them golden status
    # for the on-target S-tier brochure — then union them in (deduped). We boost ONLY the scoped hits,
    # not the already-boosted final_results, to avoid double-boosting.
    if scoped_results:
        _rank_scoped_results(scoped_results)
        scoped_results = _apply_authority_boost(scoped_results, domain)
        scoped_results = _filter_by_domain(scoped_results, domain)
        final_results = _merge_scoped_results(final_results, scoped_results)
        final_results.sort(key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)

    return _apply_year_match_boost(final_results, query, original_question)


def _is_golden_chunk(result: dict) -> bool:
    """Check if a chunk qualifies as a 'golden chunk' (S-tier with high authority)."""
    authority_boost = result.get("authority_boost", 1.0)
    priority_level = result.get("priority_level", "UNKNOWN")
    domain_tier = result.get("domain_tier", "Unknown")

    # S-tier documents with authority boost >= 2.0 are considered golden
    is_s_tier = priority_level.startswith("S") or domain_tier == "S"
    has_high_authority = authority_boost >= 2.0

    return is_s_tier and has_high_authority


def _apply_final_reranking(final_results: list[dict], query: str, config) -> list[dict]:
    """Apply golden chunk boost and final reranking."""
    # Golden Chunk Boost: Ensure S-tier documents stay at top
    final_results = _apply_golden_chunk_boost(final_results)

    # Rerank if configured - but preserve top golden chunks
    if final_results and config.kb_reranker_model_arn:
        client = _get_bedrock_client(config.aws_region)

        # Separate golden chunks from regular results
        golden_chunks = [r for r in final_results if _is_golden_chunk(r)]
        regular_chunks = [r for r in final_results if not _is_golden_chunk(r)]

        # Rerank only regular chunks, preserve golden chunk positions
        if regular_chunks:
            reranked_regular = _rerank_results(
                client,
                query,
                regular_chunks,
                config.kb_reranker_model_arn,
                max(1, config.kb_reranker_results - len(golden_chunks)),
            )
            final_results = golden_chunks + reranked_regular
        else:
            final_results = golden_chunks

    return final_results


def _apply_golden_chunk_boost(results: list[dict]) -> list[dict]:
    """Guarantee S-tier chunks at position #1."""
    if not results:
        return results

    # Separate S-tier and non-S-tier chunks
    s_tier_chunks = []
    regular_chunks = []

    for result in results:
        priority_level = result.get("priority_level", "UNKNOWN")
        domain_tier = result.get("domain_tier", "Unknown")
        is_s_tier = priority_level.startswith("S") or domain_tier == "S"

        if is_s_tier:
            result["is_golden_chunk"] = True
            s_tier_chunks.append(result)
            logger.info(
                "S-tier chunk found",
                extra={
                    "chunk": result.get("s3_key", "")[:50],
                    "authority_boost": result.get("authority_boost", 1.0),
                    "priority_level": priority_level,
                    "domain_tier": domain_tier,
                },
            )
        else:
            regular_chunks.append(result)

    # Sort S-tier by original relevance score (best first)
    s_tier_chunks.sort(key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)

    # Sort regular chunks by their scores
    regular_chunks.sort(key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)

    # S-tier chunks first, then regular chunks
    return s_tier_chunks + regular_chunks


# --- Content / parent-subdocument dedup (#698) ---
#
# The DITA ETL intentionally emits standalone note/table subdocuments while passing the
# unchanged parent chunk through, so a parent chunk and its extracted "_table_000" copy —
# different s3_keys, identical passage — both survive the s3_key-only fusion dedup and reach the
# model, wasting the final retrieval budget on a duplicate passage. This pass collapses such
# overlapping candidates into one AFTER fusion + rerank (the scope the issue names), using
# deterministic word-shingle containment so it also handles the per-chunk contextual-grounding
# prefixes that a plain whole-chunk hash would miss.

_FRONT_MATTER_RE = re.compile(r"^---\n.*?\n---\n*", re.DOTALL)
_FOCUSED_CHUNK_TYPES = frozenset({"table", "note"})


def _normalize_for_overlap(text: str) -> list[str]:
    r"""Normalize chunk text to a comparable token stream for overlap detection.

    Strips YAML front-matter, then casefolds and tokenizes with the shared ``_WORD_RE`` (``\w+``).
    Markdown table pipes / heading / list / emphasis markers are all non-word characters, so
    tokenizing already discards them; ``casefold`` (not ``lower``) keeps German ``ß``/umlaut
    folding consistent on both sides of a comparison.
    """
    if not text:
        return []
    stripped = _FRONT_MATTER_RE.sub("", text)
    return _WORD_RE.findall(stripped.casefold())


def _hash_gram(gram: str) -> int:
    """Deterministic 64-bit hash of an n-gram.

    Uses ``blake2b`` — deliberately NOT the builtin ``hash()``, which is per-process salted
    (``PYTHONHASHSEED``) and would make the dedup output non-deterministic across runs (a hard
    requirement here).
    """
    return int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")


def _shingle_set(tokens: list[str], shingle_size: int) -> frozenset[int]:
    """Hashed word n-gram shingle set; falls back to unigrams when shorter than ``shingle_size``."""
    if not tokens:
        return frozenset()
    if len(tokens) < shingle_size:
        return frozenset(_hash_gram(token) for token in tokens)
    return frozenset(_hash_gram(" ".join(tokens[i : i + shingle_size])) for i in range(len(tokens) - shingle_size + 1))


def _containment(a: frozenset[int], b: frozenset[int]) -> float:
    """Containment overlap ``|a ∩ b| / |smaller|`` — 1.0 when the smaller set is a subset of the larger."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _overlap_signature(result: dict, shingle_size: int) -> frozenset[int]:
    """Return (and cache on the result dict) the shingle signature of a result's content."""
    cached = result.get("_overlap_signature")
    if cached is not None:
        return cached
    signature = _shingle_set(_normalize_for_overlap(result.get("content", "")), shingle_size)
    result["_overlap_signature"] = signature
    return signature


def _exact_content_hash(result: dict) -> str | None:
    """blake2b of the fully normalized text; ``None`` for empty content (which never collapses)."""
    tokens = _normalize_for_overlap(result.get("content", ""))
    if not tokens:
        return None
    return hashlib.blake2b(" ".join(tokens).encode("utf-8"), digest_size=16).hexdigest()


def _is_focused_chunk(result: dict) -> bool:
    """Return True when the result is an ETL-extracted note/table subdocument (``metadata.chunk_type``)."""
    return (result.get("metadata") or {}).get("chunk_type") in _FOCUSED_CHUNK_TYPES


def _bucket_key(result: dict) -> str:
    """Overlap-test group key: ``brochure_number`` (a parent and its subdocs always share it)."""
    return (result.get("metadata") or {}).get("brochure_number") or ""


def _choose_survivor(
    kept: dict, incoming: dict, parent_unique_ratio: float, parent_context_min: float, shingle_size: int
) -> tuple[dict, dict, str]:
    """Pick which member of an overlapping pair to keep. Returns ``(survivor, dropped, rule)``.

    Deterministic survivor order (every branch collapses the pair to exactly one member, and the
    survivor always still contains the shared passage, so answer-level recall is preserved):

    1. golden guard — keep the sole ``is_golden_chunk`` member (protects the S-tier guarantee).
    2. distinct parent context — if ``parent_unique_ratio >= parent_context_min`` keep the broader
       (superset) chunk, so its non-duplicated context survives alongside the shared passage.
    3. prefer focused — else keep the sole focused note/table chunk (the parent adds little beyond it).
    4. fallback — higher ``rrf_score``; tie-break on the lexicographically smaller ``s3_key``.
    """
    kept_golden = bool(kept.get("is_golden_chunk"))
    incoming_golden = bool(incoming.get("is_golden_chunk"))
    if kept_golden != incoming_golden:
        return (kept, incoming, "golden") if kept_golden else (incoming, kept, "golden")

    if parent_unique_ratio >= parent_context_min:
        kept_size = len(_overlap_signature(kept, shingle_size))
        incoming_size = len(_overlap_signature(incoming, shingle_size))
        # Keep the larger (superset) chunk; tie → the earlier-ranked kept chunk.
        if kept_size >= incoming_size:
            return kept, incoming, "parent_context"
        return incoming, kept, "parent_context"

    kept_focused = _is_focused_chunk(kept)
    incoming_focused = _is_focused_chunk(incoming)
    if kept_focused != incoming_focused:
        return (kept, incoming, "prefer_focused") if kept_focused else (incoming, kept, "prefer_focused")

    kept_score = kept.get("rrf_score", kept.get("score", 0))
    incoming_score = incoming.get("rrf_score", incoming.get("score", 0))
    if kept_score > incoming_score:
        return kept, incoming, "score"
    if incoming_score > kept_score:
        return incoming, kept, "score"
    # Deterministic tie-break: the lexicographically smaller s3_key wins.
    if kept.get("s3_key", "") <= incoming.get("s3_key", ""):
        return kept, incoming, "score"
    return incoming, kept, "score"


def _merge_into_survivor(
    survivor: dict, dropped: dict, containment: float, parent_unique_ratio: float, rule: str
) -> None:
    """Fold a dropped duplicate into the survivor: strongest score, unioned sources, provenance trail.

    Provenance is kept INTERNAL to the result dict (never added to ``out_sources``), so the API
    contract and frontend types are unchanged; citations stay correct by construction because only
    survivors reach ``_build_retrieval_response``.
    """
    survivor["rrf_score"] = max(survivor.get("rrf_score", 0), dropped.get("rrf_score", 0))
    survivor["sources"] = set(survivor.get("sources") or set()) | set(dropped.get("sources") or set())
    provenance = survivor.setdefault("deduplicated_from", [])
    # Carry forward any provenance the dropped member itself accumulated (multi-way collapse).
    provenance.extend(dropped.get("deduplicated_from", []))
    provenance.append({
        "s3_key": dropped.get("s3_key", ""),
        "chunk_type": (dropped.get("metadata") or {}).get("chunk_type"),
        "sources": sorted(dropped.get("sources") or set()),
        "rrf_score": dropped.get("rrf_score", 0),
        "containment": round(containment, 4),
        "parent_unique_ratio": round(parent_unique_ratio, 4),
        "rule": rule,
    })


def _deduplicate_overlapping_results(results: list[dict], config) -> list[dict]:
    """Collapse candidates carrying the same substantive passage into one (deterministic, in-memory).

    Two sequential passes, both preserving post-rerank / golden-first order (no global re-sort):

    1. a global exact-content-hash pass (blake2b of the fully normalized text) collapses
       byte-identical content across buckets — this catches the semantic-``s3_key`` vs
       BM25-``chunk_id`` "same content, different key form" duplicate that fusion misses;
    2. a ``brochure_number``-bucketed word-shingle containment pass collapses a focused note/table
       subdocument into (or against) its parent chunk. Bucketing is near-linear on the ≤30-result
       final set and structurally prevents collapsing two unrelated brochures that coincidentally
       overlap.
    """
    if not config.content_dedup_enabled or len(results) < 2:
        return results

    shingle_size = config.content_dedup_shingle_size
    containment_min = config.content_dedup_containment_min
    parent_context_min = config.content_dedup_parent_context_min

    with _get_otel_tracer().start_as_current_span("retrieval.dedup") as span:
        span.set_attribute("retrieval.dedup.input_count", len(results))

        # Pass 1 — global exact-content-hash collapse (byte-identical content, across buckets).
        after_exact: list[dict] = []
        by_hash: dict[str, int] = {}
        for result in results:
            content_hash = _exact_content_hash(result)
            if content_hash is not None and content_hash in by_hash:
                slot = by_hash[content_hash]
                survivor, dropped, rule = _choose_survivor(
                    after_exact[slot], result, 0.0, parent_context_min, shingle_size
                )
                _merge_into_survivor(survivor, dropped, 1.0, 0.0, rule)
                # Content is identical, so the hash→slot mapping stays valid regardless of winner.
                after_exact[slot] = survivor
            else:
                after_exact.append(result)
                if content_hash is not None:
                    by_hash.setdefault(content_hash, len(after_exact) - 1)

        # Pass 2 — brochure-bucketed containment collapse (parent ⇄ note/table subdocument).
        kept: list[dict] = []
        buckets: dict[str, list[int]] = defaultdict(list)
        for result in after_exact:
            signature = _overlap_signature(result, shingle_size)
            bucket = _bucket_key(result)
            match_slot: int | None = None
            match_containment = 0.0
            match_parent_unique_ratio = 0.0
            for slot in buckets[bucket]:
                other = _overlap_signature(kept[slot], shingle_size)
                containment = _containment(signature, other)
                if containment >= containment_min:
                    match_slot = slot
                    match_containment = containment
                    inter = len(signature & other)
                    larger = max(len(signature), len(other))
                    match_parent_unique_ratio = (larger - inter) / larger if larger else 0.0
                    break
            if match_slot is None:
                kept.append(result)
                # A parent and its subdocs always share brochure_number, so the survivor stays in
                # this bucket whichever member wins — no bucket-index maintenance needed on collapse.
                buckets[bucket].append(len(kept) - 1)
            else:
                survivor, dropped, rule = _choose_survivor(
                    kept[match_slot], result, match_parent_unique_ratio, parent_context_min, shingle_size
                )
                _merge_into_survivor(survivor, dropped, match_containment, match_parent_unique_ratio, rule)
                kept[match_slot] = survivor

        collapsed = len(results) - len(kept)
        span.set_attribute("retrieval.dedup.output_count", len(kept))
        span.set_attribute("retrieval.dedup.collapsed_count", collapsed)
        if collapsed:
            logger.info(
                "Content dedup collapsed overlapping retrieval results",
                extra={"input": len(results), "output": len(kept), "collapsed": collapsed},
            )
        return kept


def _resolve_result_metadata(result: dict, config) -> tuple[dict, str]:
    """Resolve metadata and source_uri for a retrieval result, fetching sidecar if needed."""
    s3_key = result["s3_key"]
    metadata = result.get("metadata", {})
    source_uri = result.get("source_uri", "")

    # For BM25-only hits: construct source_uri and fetch metadata
    if not source_uri and s3_key and config.bm25_index_bucket:
        source_uri = f"s3://{config.bm25_index_bucket}/{s3_key}"
    includes_bm25 = "bm25" in result.get("sources", set())
    immutable_bm25 = includes_bm25 and getattr(config, "retrieval_legacy_fallback", True) is False

    # Release-pinned metadata from the in-memory index: free, release-coherent,
    # and the only source available to an immutable release. Without this a hit
    # that lost its metadata upstream would be cited by its raw chunk filename.
    if not (metadata.get("name") or metadata.get("title")):
        for key, value in get_cached_chunk_metadata(s3_key, config).items():
            metadata.setdefault(key, value)

    if not metadata and includes_bm25 and not immutable_bm25 and config.bm25_index_bucket and s3_key:
        metadata = _fetch_bm25_metadata(s3_key, config)

    # Enrich metadata from S3 sidecar when custom fields are missing (e.g. S3 Vectors)
    if s3_key and config.bm25_index_bucket and not metadata.get("brochure_url") and not immutable_bm25:
        sidecar = _fetch_s3_metadata_sidecar(s3_key, config.bm25_index_bucket, config)
        for key, value in sidecar.items():
            metadata.setdefault(key, value)

    return metadata, source_uri or "Unknown source"


def _build_retrieval_response(
    final_results: list[dict], config, out_sources: list[dict], domain: str | None = None
) -> str:
    """Build formatted response and populate out_sources from fused results."""
    formatted_results = []

    # Offset sourceIndex so it stays globally unique across multiple KB tool calls in one turn
    offset = len(out_sources)

    for i, result in enumerate(final_results, 1):
        global_index = offset + i
        metadata, source_uri = _resolve_result_metadata(result, config)

        content = result["content"]
        display_name = get_display_name(metadata, source_uri)
        if not (metadata.get("name") or metadata.get("title")):
            # No resolvable title: the citation shows a derived label instead of
            # the official brochure title, and authority boost is unavailable.
            logger.warning(
                "Source metadata unresolved — citation falls back to a derived label",
                extra={"s3_key": result.get("s3_key", "")[:120], "display_name": display_name},
            )
        # Prefer the short-form URL (see chunk_markdown._derive_short_brochure_url) so the
        # frontend shows short links; fall back to the long form for chunks ingested before
        # the short-URL migration or document types the short form doesn't apply to.
        brochure_url = metadata.get("brochure_url_short") or metadata.get("brochure_url")
        brochure_number = metadata.get("brochure_number")
        publishing_date = metadata.get("publishing_date")
        category = metadata.get("category")
        # Non-sensitive, stable document identity (folder/stem, never the S3 URI itself)
        # shared by every chunk of the same source document — see _doc_key. Security fix
        # #871: the S3 URI must never reach the API response or DynamoDB storage.
        document_id = _doc_key(result.get("s3_key", ""), source_uri)

        out_sources.append({
            "content": content,
            "contentType": "text",
            "rank": i,
            "title": display_name,
            "documentId": document_id,
            "sourceName": display_name,
            "sourceIndex": global_index,
            "brochureUrl": brochure_url,
            "brochureNumber": brochure_number,
            "publishingDate": publishing_date,
            "category": category,
            "authorityBoost": result.get("authority_boost", 1.0),
            "priorityLevel": result.get("priority_level", "UNKNOWN"),
            "originalScore": result.get("original_score", 0),
            "domainTier": result.get("domain_tier", "Unknown"),
            "domain": result.get("domain", "Unknown"),
            "domainClassified": domain or "Unknown",
            "anchorSelected": result.get("is_anchor", False),
            "isGoldenChunk": result.get("is_golden_chunk", False),
            "retrievalReleaseId": getattr(config, "retrieval_release_id", "legacy-environment"),
        })

        priority_level = result.get("priority_level", "UNKNOWN")
        authority_boost = result.get("authority_boost", 1.0)
        is_golden = result.get("is_golden_chunk", False)
        domain_tier = result.get("domain_tier", "Unknown")

        priority_indicator = ""
        if is_golden:
            priority_indicator = f" ⭐GOLDEN⭐ (Tier: {domain_tier}, Authority: {authority_boost:.1f})"
        elif priority_level != "UNKNOWN":
            priority_indicator = f" (Priorität: {priority_level}, Authority: {authority_boost:.1f})"

        formatted_results.append(f"[Source {global_index}: {display_name}{priority_indicator}]\n{content}\n")

    combined = "\n".join(formatted_results)
    domain_context = f"\n\n[DOMAIN: {domain}]" if domain else ""
    return f"Found {len(final_results)} relevant document(s):\n\n{combined}{domain_context}"


_OUT_OF_SCOPE_MESSAGE = (
    "Diese Frage liegt außerhalb meines Zuständigkeitsbereichs als Assistentin der "
    "Deutschen Rentenversicherung. Bitte wenden Sie sich an die entsprechenden Fachstellen."
)


def _has_lexical_hit(query: str, config) -> bool:
    """Return True if BM25 finds a genuine lexical match for the query in the corpus.

    Used to second-guess an 'off-topic' (themenfremd) classification: real DRV terms appear
    in the corpus and score > 0 even when the classifier doesn't recognise them (e.g. IRENA),
    whereas truly off-topic terms (e.g. "Wetter") don't appear at all. Returns False when BM25
    is disabled, so the out-of-scope message is preserved in semantic-only deployments.
    """
    if not config.bm25_enabled:
        return False
    try:
        return bool(bm25_search(query, top_k=1, retrieval_snapshot=config))
    except Exception:
        logger.exception("Lexical relevance check failed")
        return False


@tracer.capture_method(capture_response=False)
def search_knowledge_base(
    query: str, out_sources: list[dict], call_num: int = 1, domain: str = "sonstiges", original_question: str = ""
) -> str:
    """Search the knowledge base for information about DRV pension insurance.

    Use this tool to find factual information from official DRV documentation
    about topics like pension calculations, retirement age, insurance requirements,
    and other pension-related questions.

    Args:
        query: Concise keyword-focused retrieval query optimized for semantic search
        out_sources: Mutable list to append retrieved source metadata to
        call_num: KB call counter for observability
        domain: Classified domain (rente|reha|versicherung|sonstiges|themenfremd|mehrdeutig)
        original_question: Raw user question. Used as a second retrieval query fused below the
            rephrased ``query`` (see ``_ORIGINAL_QUERY_WEIGHT``), and for year-match boosting —
            the rephrase routinely drops the birth year (esp. two-digit "Jahrgang 63" forms)

    Returns:
        Relevant information from the knowledge base, or indication if nothing found

    """
    # Resolve exactly once. The shallow request copy freezes the complete
    # semantic + BM25 coordinate set even if SSM changes mid-request.
    config = snapshot_retrieval_config(get_config())

    if not config.knowledge_base_id:
        logger.warning("KNOWLEDGE_BASE_ID not configured", extra={"query": query[:50]})
        return "Knowledge base not available - cannot search documentation."

    # An 'off-topic' classification is a fallible model guess — unknown DRV terms like IRENA
    # get mislabeled themenfremd. Probe cheaply with BM25 first: a genuine lexical match means
    # the term really is in the DRV corpus (rescue it), while no match confirms the question is
    # off-topic — refuse without paying for the semantic search.
    if domain == Domain.THEMENFREMD and not _has_lexical_hit(query, config):
        logger.info(
            "Off-topic query with no lexical match — returning out-of-scope message",
            extra={"query": query[:50]},
        )
        return _OUT_OF_SCOPE_MESSAGE

    retrieval_query = query
    if config.hyde_enabled:
        retrieval_query = generate_hypothetical_document(retrieval_query, config.hyde_model_id, config.aws_region)

    try:
        logger.info(
            "KB retrieval starting",
            extra={
                "query": query[:50],
                "domain": domain,
                "call_num": call_num,
                "hyde": config.hyde_enabled,
                "release_id": config.retrieval_release_id,
            },
        )

        final_results = _perform_search_and_enhancement(query, retrieval_query, config, domain, original_question)
        final_results = _apply_final_reranking(final_results, query, config)
        # Collapse duplicate note/table + parent passages so a single substantive passage does not
        # consume multiple slots of the model-facing budget (#698). After rerank, before response.
        final_results = _deduplicate_overlapping_results(final_results, config)

    except Exception as e:
        logger.exception("Error retrieving from knowledge base", extra={"query": query[:50]})
        return f"Error searching knowledge base: {e!s}"
    else:
        if not final_results:
            return "No relevant information found in the knowledge base for this query."

        response = _build_retrieval_response(final_results, config, out_sources, domain)
        return response
