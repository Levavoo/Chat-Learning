"""Evaluate content / parent-subdocument dedup (#698): collapse, unique-passage, recall.

Runs each query twice through ``search_knowledge_base`` (dedup off vs on) against a
live KB and reports collapse_count and answer_recall per query.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backend_orchestrator.config import Config
from backend_orchestrator.retrieval_manifest import reset_retrieval_manifest_cache
from backend_orchestrator.tools.kb_retrieval import search_knowledge_base

_DEFAULT_QUERIES: list[dict] = [
    {
        "query": "Was ist Einkommen und was nicht bei der Grundsicherung",
        "domain": "rente",
        "expect": [],
    },
    {"query": "Rente mit 63 Voraussetzungen", "domain": "rente", "expect": []},
    {"query": "Was ist IRENA in der Reha-Nachsorge", "domain": "reha", "expect": []},
    {"query": "freiwillige Beiträge rückwirkend nachzahlen", "domain": "versicherung", "expect": []},
]


def _reset_config() -> None:
    """Force config + retrieval-manifest cache to re-read the environment."""
    Config._instance = None
    reset_retrieval_manifest_cache()


def _run_query(query: str, domain: str, *, dedup_enabled: bool) -> list[dict]:
    """Run one query through the real retrieval pipeline and return the model-facing sources."""
    os.environ["CONTENT_DEDUP_ENABLED"] = "true" if dedup_enabled else "false"
    _reset_config()
    out_sources: list[dict] = []
    search_knowledge_base(query, out_sources, domain=domain, original_question=query)
    return out_sources


def _answer_recall(sources: list[dict], expected: list[str]) -> float | None:
    """Fraction of expected substrings still present after dedup."""
    if not expected:
        return None
    haystack = "\n".join(s.get("content", "") for s in sources).casefold()
    found = sum(1 for needle in expected if needle.casefold() in haystack)
    return round(found / len(expected), 4)


def _evaluate(queries: list[dict]) -> dict:
    """Compare dedup off vs on and build the JSON report."""
    per_query: list[dict] = []
    for item in queries:
        query = item["query"]
        domain = item.get("domain", "sonstiges")
        expect = item.get("expect", [])

        off_sources = _run_query(query, domain, dedup_enabled=False)
        on_sources = _run_query(query, domain, dedup_enabled=True)

        result_count = len(off_sources)
        unique_passage_count = len(on_sources)
        per_query.append({
            "query": query,
            "domain": domain,
            "result_count": result_count,
            "unique_passage_count": unique_passage_count,
            "collapse_count": result_count - unique_passage_count,
            "answer_recall": _answer_recall(on_sources, expect),
        })

    total_collapsed = sum(q["collapse_count"] for q in per_query)
    recalls = [q["answer_recall"] for q in per_query if q["answer_recall"] is not None]
    return {
        "queries": per_query,
        "totals": {
            "queries": len(per_query),
            "collapsed_slots": total_collapsed,
            "mean_answer_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate #698 content dedup (dedup off vs on).")
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help="JSON list of {query, domain, expect[]} objects (defaults to a built-in set).",
    )
    args = parser.parse_args()

    queries = _DEFAULT_QUERIES
    if args.queries is not None:
        queries = json.loads(args.queries.read_text(encoding="utf-8"))

    report = _evaluate(queries)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
