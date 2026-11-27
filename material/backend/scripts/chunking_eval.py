#!/usr/bin/env python3
"""Hyperparameter search over chunking params via Titan Embed v2 geometry metrics."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parents[2] / "cdk" / "seed-data" / "agent-search-index" / "documents"
CACHE_DIR = Path(__file__).resolve().parents[1] / "scripts" / ".chunking_eval_cache"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIM = 1024
REGION = os.environ.get("AWS_REGION", "eu-central-1")


def load_documents() -> list[dict]:
    """Load all agent-search-index JSON documents."""
    docs = []
    for f in sorted(DOCS_DIR.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
            docs.append(doc)
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
class ChunkResult:
    doc_id: str
    chunks: list[str]


@dataclass
class ChunkingConfig:
    strategy: str
    section_split_threshold: int = 3000
    section_overlap: int = 300
    min_divs_for_hierarchical: int = 3
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = f"{self.strategy}_t{self.section_split_threshold}_o{self.section_overlap}"


def chunk_document(markdown: str, config: ChunkingConfig) -> list[str]:
    """Chunk a markdown document using the given config."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from etl.util.chunking.flat_section_strategy import FlatSectionChunkingStrategy
    from etl.util.chunking.hierarchical_strategy import HierarchicalChunkingStrategy

    if config.strategy == "hierarchical" and _has_h3(markdown, config.min_divs_for_hierarchical):
        strategy = HierarchicalChunkingStrategy(
            section_split_threshold=config.section_split_threshold,
            section_overlap=config.section_overlap,
        )
    else:
        strategy = FlatSectionChunkingStrategy(
            section_split_threshold=config.section_split_threshold,
            section_overlap=config.section_overlap,
            # Eval runs on PDF content; enable the PDF-scoped fallback.
            enable_headerless_fallback=True,
        )

    chunks = strategy.chunk(markdown, metadata={})
    return [c.content for c in chunks if c.content.strip()]


def _has_h3(text: str, threshold: int) -> bool:
    return text.count("\n### ") >= threshold


def get_bedrock_client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=REGION)


def embed_texts(texts: list[str], client) -> np.ndarray:
    """Embed texts using Titan Embed v2 with concurrent workers."""
    import concurrent.futures
    import threading

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


@dataclass
class EvalMetrics:
    config_name: str
    num_chunks: int = 0
    avg_chunk_chars: float = 0.0
    std_chunk_chars: float = 0.0
    min_chunk_chars: int = 0
    max_chunk_chars: int = 0
    intra_doc_similarity: float = 0.0  # higher = more cohesive
    inter_doc_similarity: float = 0.0  # lower = better separation
    mean_margin: float = 0.0  # intra - inter
    silhouette_score: float = 0.0
    avg_pairwise_similarity: float = 0.0
    score_variance: float = 0.0
    composite_score: float = 0.0


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

    # For inter-doc: sample pairs of documents, take up to 3 chunks each
    inter_sims: list[float] = []
    doc_ids = list(doc_indices.keys())
    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            pairs = [(a, b) for a in doc_indices[doc_ids[i]][:3] for b in doc_indices[doc_ids[j]][:3]]
            inter_sims.extend(sim_matrix[a, b] for a, b in pairs)
            if len(inter_sims) >= 10000:
                return intra_sims, inter_sims

    return intra_sims, inter_sims


def compute_metrics(doc_chunks: list[ChunkResult], embeddings: np.ndarray, config_name: str) -> EvalMetrics:
    """Compute all embedding quality metrics."""
    metrics = EvalMetrics(config_name=config_name)

    all_chunks = []
    doc_labels = []
    for dc in doc_chunks:
        for chunk in dc.chunks:
            all_chunks.append(chunk)
            doc_labels.append(dc.doc_id)

    if not all_chunks:
        return metrics

    chunk_lens = [len(c) for c in all_chunks]
    metrics.num_chunks = len(all_chunks)
    metrics.avg_chunk_chars = float(np.mean(chunk_lens))
    metrics.std_chunk_chars = float(np.std(chunk_lens))
    metrics.min_chunk_chars = min(chunk_lens)
    metrics.max_chunk_chars = max(chunk_lens)

    if embeddings.shape[0] < 2:
        return metrics

    # Titan embeddings are already normalized.
    sim_matrix = embeddings @ embeddings.T
    n = len(doc_labels)

    intra_sims, inter_sims = _compute_doc_similarities(sim_matrix, doc_labels)

    if intra_sims:
        metrics.intra_doc_similarity = float(np.mean(intra_sims))
    if inter_sims:
        metrics.inter_doc_similarity = float(np.mean(inter_sims))
    metrics.mean_margin = metrics.intra_doc_similarity - metrics.inter_doc_similarity

    triu_indices = np.triu_indices(n, k=1)
    all_sims = sim_matrix[triu_indices]
    metrics.avg_pairwise_similarity = float(np.mean(all_sims))
    metrics.score_variance = float(np.var(all_sims))

    metrics.silhouette_score = _compute_silhouette(sim_matrix, doc_labels)

    metrics.composite_score = (
        0.4 * metrics.mean_margin
        + 0.3 * max(0, metrics.silhouette_score)
        + 0.2 * metrics.score_variance * 10
        + 0.1 * (1.0 - metrics.avg_pairwise_similarity)
    )

    return metrics


def _compute_silhouette(sim_matrix: np.ndarray, labels: list[str]) -> float:
    """Silhouette score from a precomputed cosine similarity matrix."""
    n = len(labels)
    if n < 3:
        return 0.0

    dist_matrix = 1.0 - sim_matrix

    unique_labels = list(set(labels))
    if len(unique_labels) < 2:
        return 0.0

    label_to_idx = {label: i for i, label in enumerate(unique_labels)}
    label_indices = [label_to_idx[lab] for lab in labels]

    clusters: dict[int, list[int]] = {}
    for i, li in enumerate(label_indices):
        clusters.setdefault(li, []).append(i)

    sample_indices = list(range(n)) if n <= 500 else list(np.random.choice(n, 500, replace=False))

    silhouettes = []
    for i in sample_indices:
        ci = label_indices[i]
        cluster_members = [j for j in clusters[ci] if j != i]

        if not cluster_members:
            continue

        a_i = np.mean([dist_matrix[i, j] for j in cluster_members])

        b_i = float("inf")
        for ck, members in clusters.items():
            if ck == ci or not members:
                continue
            mean_dist = np.mean([dist_matrix[i, j] for j in members[:20]])
            b_i = min(b_i, mean_dist)

        if b_i == float("inf"):
            continue

        s_i = (b_i - a_i) / max(a_i, b_i) if max(a_i, b_i) > 0 else 0
        silhouettes.append(s_i)

    return float(np.mean(silhouettes)) if silhouettes else 0.0


def generate_configs() -> list[ChunkingConfig]:
    """Generate the hyperparameter search space."""
    configs = []

    thresholds = [1000, 1500, 2000, 2500, 3000, 4000, 5000]
    overlaps = [0, 100, 200, 300, 500]

    for threshold, overlap in product(thresholds, overlaps):
        if overlap >= threshold:
            continue
        configs.append(ChunkingConfig(strategy="flat", section_split_threshold=threshold, section_overlap=overlap))

    for min_divs in [2, 3, 5]:
        configs.append(
            ChunkingConfig(
                strategy="hierarchical",
                min_divs_for_hierarchical=min_divs,
                name=f"hierarchical_mindivs{min_divs}",
            )
        )

    return configs


def run_evaluation(args: argparse.Namespace) -> None:
    """Run the full hyperparameter search."""
    docs = load_documents()
    configs = generate_configs()
    logger.info(f"Testing {len(configs)} chunking configurations across {len(docs)} documents")

    client = get_bedrock_client()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    results: list[EvalMetrics] = []

    for ci, config in enumerate(configs):
        logger.info(f"\n[{ci + 1}/{len(configs)}] Evaluating: {config.name}")

        # Chunk all documents
        doc_chunks: list[ChunkResult] = []
        all_chunk_texts: list[str] = []

        for doc in docs:
            markdown = doc_to_markdown(doc)
            chunks = chunk_document(markdown, config)
            doc_chunks.append(ChunkResult(doc_id=doc["doc_id"], chunks=chunks))
            all_chunk_texts.extend(chunks)

        logger.info(f"  Produced {len(all_chunk_texts)} chunks from {len(docs)} documents")

        if not all_chunk_texts:
            logger.warning("  No chunks produced, skipping")
            continue

        # Embed (with caching)
        cache_file = CACHE_DIR / f"{config.name}_embeddings.npy"
        if args.skip_embed and cache_file.exists():
            logger.info(f"  Loading cached embeddings from {cache_file.name}")
            embeddings = np.load(cache_file)
        else:
            logger.info(f"  Embedding {len(all_chunk_texts)} chunks via Titan Embed v2...")
            embeddings = embed_texts(all_chunk_texts, client)
            np.save(cache_file, embeddings)
            logger.info(f"  Cached embeddings to {cache_file.name}")

        # Compute metrics
        metrics = compute_metrics(doc_chunks, embeddings, config.name)
        results.append(metrics)

        logger.info(
            f"  Results: margin={metrics.mean_margin:.4f} "
            f"silhouette={metrics.silhouette_score:.4f} "
            f"composite={metrics.composite_score:.4f} "
            f"chunks={metrics.num_chunks} "
            f"avg_size={metrics.avg_chunk_chars:.0f}"
        )

    results.sort(key=lambda m: m.composite_score, reverse=True)

    top_n = args.top or len(results)
    print("\n" + "=" * 120)
    print(f"{'CHUNKING HYPERPARAMETER SEARCH RESULTS':^120}")
    print("=" * 120)
    print(
        f"{'Rank':<5}{'Config':<30}{'Chunks':<8}{'AvgSize':<9}"
        f"{'IntraDoc':<10}{'InterDoc':<10}{'Margin':<9}"
        f"{'Silhouette':<12}{'Variance':<10}{'Composite':<10}"
    )
    print("-" * 120)

    for i, m in enumerate(results[:top_n]):
        print(
            f"{i + 1:<5}{m.config_name:<30}{m.num_chunks:<8}{m.avg_chunk_chars:<9.0f}"
            f"{m.intra_doc_similarity:<10.4f}{m.inter_doc_similarity:<10.4f}{m.mean_margin:<9.4f}"
            f"{m.silhouette_score:<12.4f}{m.score_variance:<10.6f}{m.composite_score:<10.4f}"
        )

    print("-" * 120)
    print(f"\nBest config: {results[0].config_name} (composite={results[0].composite_score:.4f})")
    print("Current config: flat_t3000_o300")

    current = next((m for m in results if m.config_name == "flat_t3000_o300"), None)
    if current:
        current_rank = results.index(current) + 1
        print(f"Current config rank: {current_rank}/{len(results)}")

    results_file = CACHE_DIR / "results.json"
    results_json = []
    for m in results:
        results_json.append({
            "config_name": m.config_name,
            "num_chunks": m.num_chunks,
            "avg_chunk_chars": round(m.avg_chunk_chars, 1),
            "std_chunk_chars": round(m.std_chunk_chars, 1),
            "min_chunk_chars": m.min_chunk_chars,
            "max_chunk_chars": m.max_chunk_chars,
            "intra_doc_similarity": round(m.intra_doc_similarity, 5),
            "inter_doc_similarity": round(m.inter_doc_similarity, 5),
            "mean_margin": round(m.mean_margin, 5),
            "silhouette_score": round(m.silhouette_score, 5),
            "avg_pairwise_similarity": round(m.avg_pairwise_similarity, 5),
            "score_variance": round(m.score_variance, 6),
            "composite_score": round(m.composite_score, 5),
        })
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_json, f, indent=2, ensure_ascii=False)
    print(f"\nFull results saved to: {results_file}")


def main():
    parser = argparse.ArgumentParser(description="Chunking strategy hyperparameter search")
    parser.add_argument("--skip-embed", action="store_true", help="Reuse cached embeddings")
    parser.add_argument("--top", type=int, default=None, help="Show top N results")
    args = parser.parse_args()
    run_evaluation(args)


if __name__ == "__main__":
    main()
