#!/usr/bin/env python3
"""Contextual embeddings eval: per-chunk LLM context + chunk, embedded via Titan Embed v2."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "agent-search-index" / "documents"
CACHE_DIR = Path(__file__).resolve().parents[1] / "scripts" / ".chunking_eval_cache"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIM = 1024
CONTEXT_MODEL_ID = "openai.gpt-oss-120b-1:0"
REGION = os.environ.get("AWS_REGION", "eu-central-1")

DOCUMENT_CONTEXT_PROMPT = """<document>
{doc_content}
</document>"""

CHUNK_CONTEXT_PROMPT = """Here is the chunk we want to situate within the whole document
<chunk>
{chunk_content}
</chunk>

Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk.
Answer only with the succinct context and nothing else. Answer in German."""


def load_documents() -> list[dict]:
    """Load all agent-search-index JSON documents."""
    docs = []
    for f in sorted(DOCS_DIR.glob("*.json")):
        with open(f) as fh:
            docs.append(json.load(fh))
    logger.info(f"Loaded {len(docs)} documents")
    return docs


def doc_to_markdown(doc: dict) -> str:
    """Convert agent-search-index JSON to markdown."""
    lines = [f"# {doc.get('title', doc['doc_id'])}"]
    for section in doc.get("sections", []):
        title = section.get("title", "")
        content = section.get("content", "")
        if title:
            lines.append(f"\n## {title}\n")
        if content:
            lines.append(content)
    return "\n".join(lines)


@dataclass
class ChunkWithContext:
    doc_id: str
    chunk_content: str
    context: str
    embedded_text: str


def chunk_document_flat(markdown: str, threshold: int = 2500, overlap: int = 300) -> list[str]:
    """Chunk using the flat section strategy."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etl.util.chunking.flat_section_strategy import FlatSectionChunkingStrategy

    # Eval runs on PDF content; enable the PDF-scoped headerless fallback.
    strategy = FlatSectionChunkingStrategy(
        section_split_threshold=threshold, section_overlap=overlap, enable_headerless_fallback=True
    )
    chunks = strategy.chunk(markdown, metadata={})
    return [c.content for c in chunks if c.content.strip()]


def generate_chunk_context(doc_content: str, chunk_content: str, client) -> str:
    """Generate situating context for a chunk via Bedrock Converse."""
    try:
        response = client.converse(
            modelId=CONTEXT_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": DOCUMENT_CONTEXT_PROMPT.format(doc_content=doc_content[:50000])},
                        {"text": CHUNK_CONTEXT_PROMPT.format(chunk_content=chunk_content)},
                    ],
                }
            ],
            inferenceConfig={"temperature": 0.0, "maxTokens": 200},
        )
    except Exception as e:
        logger.warning(f"Context generation failed: {e}")
        return ""
    # gpt-oss-120b returns reasoning + text blocks; pick the text block.
    content_blocks = response["output"]["message"]["content"]
    for block in reversed(content_blocks):
        if "text" in block:
            return block["text"].strip()
    return ""


def _get_local_client(local):
    import boto3

    if not hasattr(local, "client"):
        local.client = boto3.client("bedrock-runtime", region_name=REGION)
    return local.client


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed texts using Titan Embed v2 with concurrent workers."""
    import boto3

    max_workers = 20
    local = threading.local()

    def _embed_one(text: str) -> list[float]:
        if not hasattr(local, "client"):
            local.client = boto3.client("bedrock-runtime", region_name=REGION)
        truncated = text[:20000]
        body = json.dumps({"inputText": truncated, "dimensions": EMBEDDING_DIM, "normalize": True})
        try:
            response = local.client.invoke_model(modelId=EMBEDDING_MODEL_ID, body=body, contentType="application/json")
            result = json.loads(response["body"].read())
            return result["embedding"]
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            return [0.0] * EMBEDDING_DIM

    logger.info(f"  Embedding {len(texts)} chunks with {max_workers} workers...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_embed_one, t): i for i, t in enumerate(texts)}
        results_map: dict[int, list[float]] = {}
        for done_count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            idx = futures[future]
            results_map[idx] = future.result()
            if done_count % 100 == 0:
                logger.info(f"  Embedded {done_count}/{len(texts)} chunks")

    embeddings = [results_map[i] for i in range(len(texts))]
    return np.array(embeddings, dtype=np.float32)


def _compute_doc_similarities(sim_matrix: np.ndarray, doc_labels: list[str]) -> tuple[list[float], list[float]]:
    """Compute intra-document and inter-document cosine similarities."""
    doc_indices: dict[str, list[int]] = {}
    for i, label in enumerate(doc_labels):
        doc_indices.setdefault(label, []).append(i)

    intra_sims: list[float] = []
    for _doc_id, indices in doc_indices.items():
        if len(indices) > 1:
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    intra_sims.append(sim_matrix[indices[i], indices[j]])

    inter_sims: list[float] = []
    doc_ids = list(doc_indices.keys())
    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            pairs = [(a, b) for a in doc_indices[doc_ids[i]][:3] for b in doc_indices[doc_ids[j]][:3]]
            inter_sims.extend(sim_matrix[a, b] for a, b in pairs)
            if len(inter_sims) >= 10000:
                return intra_sims, inter_sims

    return intra_sims, inter_sims


def compute_metrics(doc_labels: list[str], embeddings: np.ndarray, config_name: str) -> dict:
    """Compute embedding quality metrics."""
    sim_matrix = embeddings @ embeddings.T
    n = len(doc_labels)

    intra_sims, inter_sims = _compute_doc_similarities(sim_matrix, doc_labels)

    intra_doc = float(np.mean(intra_sims)) if intra_sims else 0.0
    inter_doc = float(np.mean(inter_sims)) if inter_sims else 0.0
    margin = intra_doc - inter_doc

    triu_indices = np.triu_indices(n, k=1)
    all_sims = sim_matrix[triu_indices]
    variance = float(np.var(all_sims))

    return {
        "config": config_name,
        "num_chunks": n,
        "intra_doc_similarity": round(intra_doc, 5),
        "inter_doc_similarity": round(inter_doc, 5),
        "mean_margin": round(margin, 5),
        "score_variance": round(variance, 6),
    }


def _generate_contexts(docs: list[dict], chunks_by_doc: dict[str, list[str]]) -> dict[str, list[str]]:
    """Generate per-chunk situating contexts via LLM."""
    import boto3

    local = threading.local()

    def _gen_context(doc_id: str, chunk: str) -> str:
        if not hasattr(local, "client"):
            local.client = boto3.client("bedrock-runtime", region_name=REGION)
        doc_content = doc_to_markdown(next(d for d in docs if d["doc_id"] == doc_id))
        return generate_chunk_context(doc_content, chunk, local.client)

    contexts_by_doc: dict[str, list[str]] = {doc_id: [""] * len(chunks) for doc_id, chunks in chunks_by_doc.items()}
    tasks = [(doc_id, idx, chunk) for doc_id, chunks in chunks_by_doc.items() for idx, chunk in enumerate(chunks)]

    logger.info(f"Generating {len(tasks)} contexts with 10 workers via {CONTEXT_MODEL_ID}...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_gen_context, doc_id, chunk): (doc_id, idx) for doc_id, idx, chunk in tasks}
        for done_count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            doc_id, idx = futures[future]
            try:
                contexts_by_doc[doc_id][idx] = future.result()
            except Exception as e:
                logger.warning(f"Context failed for {doc_id}[{idx}]: {e}")
            if done_count % 50 == 0:
                logger.info(f"  Generated {done_count}/{len(tasks)} contexts")

    return contexts_by_doc


def run(args: argparse.Namespace) -> None:
    """Run contextual embeddings evaluation."""
    docs = load_documents()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Chunking documents with flat_t2500_o300...")
    chunks_by_doc: dict[str, list[str]] = {}
    for doc in docs:
        md = doc_to_markdown(doc)
        chunks = chunk_document_flat(md, threshold=2500, overlap=300)
        chunks_by_doc[doc["doc_id"]] = chunks

    total_chunks = sum(len(c) for c in chunks_by_doc.values())
    logger.info(f"Total chunks: {total_chunks}")

    contexts_cache = CACHE_DIR / "contextual_contexts.json"
    if args.skip_llm and contexts_cache.exists():
        logger.info("Loading cached contexts...")
        with open(contexts_cache) as f:
            contexts_by_doc = json.load(f)
    else:
        contexts_by_doc = _generate_contexts(docs, chunks_by_doc)
        with open(contexts_cache, "w") as f:
            json.dump(contexts_by_doc, f, ensure_ascii=False)
        logger.info(f"Cached contexts to {contexts_cache}")

    contextual_texts = []
    baseline_texts = []
    doc_labels = []

    for doc_id, chunks in chunks_by_doc.items():
        contexts = contexts_by_doc.get(doc_id, [""] * len(chunks))
        for idx, chunk in enumerate(chunks):
            ctx = contexts[idx] if idx < len(contexts) else ""
            contextual_texts.append(f"{ctx}\n\n{chunk}" if ctx else chunk)
            baseline_texts.append(chunk)
            doc_labels.append(doc_id)

    baseline_cache = CACHE_DIR / "baseline_t2500_embeddings.npy"
    contextual_cache = CACHE_DIR / "contextual_embeddings.npy"

    if args.skip_embed and baseline_cache.exists():
        logger.info("Loading cached baseline embeddings...")
        baseline_emb = np.load(baseline_cache)
    else:
        logger.info("Embedding baseline chunks (no context)...")
        baseline_emb = embed_texts(baseline_texts)
        np.save(baseline_cache, baseline_emb)

    if args.skip_embed and contextual_cache.exists():
        logger.info("Loading cached contextual embeddings...")
        contextual_emb = np.load(contextual_cache)
    else:
        logger.info("Embedding contextual chunks (context + chunk)...")
        contextual_emb = embed_texts(contextual_texts)
        np.save(contextual_cache, contextual_emb)

    baseline_metrics = compute_metrics(doc_labels, baseline_emb, "baseline_t2500_o300")
    contextual_metrics = compute_metrics(doc_labels, contextual_emb, "contextual_t2500_o300")

    print("\n" + "=" * 80)
    print(f"{'CONTEXTUAL EMBEDDINGS COMPARISON':^80}")
    print("=" * 80)
    print(f"{'Metric':<25}{'Baseline (chunk only)':<30}{'Contextual (context+chunk)':<30}")
    print("-" * 80)
    for key in ["num_chunks", "intra_doc_similarity", "inter_doc_similarity", "mean_margin", "score_variance"]:
        print(f"{key:<25}{baseline_metrics[key]:<30}{contextual_metrics[key]:<30}")
    print("-" * 80)

    margin_improvement = contextual_metrics["mean_margin"] - baseline_metrics["mean_margin"]
    pct = (margin_improvement / baseline_metrics["mean_margin"] * 100) if baseline_metrics["mean_margin"] else 0
    print(f"\nMargin improvement: {margin_improvement:+.5f} ({pct:+.1f}%)")
    print(f"Model used for context: {CONTEXT_MODEL_ID}")

    results_file = CACHE_DIR / "contextual_comparison.json"
    with open(results_file, "w") as f:
        json.dump({"baseline": baseline_metrics, "contextual": contextual_metrics}, f, indent=2)
    print(f"Results saved to: {results_file}")


def main():
    """Run contextual embeddings evaluation CLI."""
    parser = argparse.ArgumentParser(description="Contextual embeddings evaluation (Anthropic-style)")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-embed", action="store_true")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
