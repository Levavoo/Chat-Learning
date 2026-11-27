#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from backend_orchestrator.tools.kb_retrieval import _apply_golden_chunk_boost


def test_s_tier_ranking():
    test_results = [
        {
            "s3_key": "regular_high_score",
            "content": "High scoring regular content",
            "rrf_score": 0.95,
            "priority_level": "A2",
            "domain_tier": "A",
            "authority_boost": 1.2,
        },
        {
            "s3_key": "s_tier_medium_score",
            "content": "Medium scoring S-tier content",
            "rrf_score": 0.7,
            "priority_level": "S1",
            "domain_tier": "S",
            "authority_boost": 2.0,
        },
        {
            "s3_key": "regular_medium_score",
            "content": "Medium scoring regular content",
            "rrf_score": 0.8,
            "priority_level": "E3",
            "domain_tier": "E",
            "authority_boost": 1.5,
        },
        {
            "s3_key": "s_tier_high_score",
            "content": "High scoring S-tier content",
            "rrf_score": 0.9,
            "priority_level": "S2",
            "domain_tier": "S",
            "authority_boost": 2.5,
        },
        {
            "s3_key": "regular_low_score",
            "content": "Low scoring regular content",
            "rrf_score": 0.4,
            "priority_level": "A4",
            "domain_tier": "A",
            "authority_boost": 1.0,
        },
    ]

    print("BEFORE ranking:")
    for i, result in enumerate(test_results, 1):
        print(f"  {i}. {result['s3_key']} (score: {result['rrf_score']}, tier: {result['domain_tier']})")

    ranked_results = _apply_golden_chunk_boost(test_results.copy())

    print("\nAFTER S-tier ranking:")
    for i, result in enumerate(ranked_results, 1):
        tier = result.get("domain_tier", "Unknown")
        is_golden = result.get("is_golden_chunk", False)
        golden_marker = " ⭐GOLDEN⭐" if is_golden else ""
        print(f"  {i}. {result['s3_key']} (score: {result['rrf_score']}, tier: {tier}){golden_marker}")

    s_tier_positions = []
    for i, result in enumerate(ranked_results):
        tier = result.get("domain_tier", "Unknown")
        priority = result.get("priority_level", "UNKNOWN")
        is_s_tier = priority.startswith("S") or tier == "S"
        if is_s_tier:
            s_tier_positions.append(i + 1)

    print(f"\nS-tier chunks found at positions: {s_tier_positions}")

    assert len(ranked_results) == 5, f"Expected 5 results, got {len(ranked_results)}"

    first_chunk = ranked_results[0]
    first_tier = first_chunk.get("domain_tier", "Unknown")
    first_priority = first_chunk.get("priority_level", "UNKNOWN")
    is_first_s_tier = first_priority.startswith("S") or first_tier == "S"

    assert is_first_s_tier, f"First chunk should be S-tier, got tier: {first_tier}, priority: {first_priority}"

    assert s_tier_positions == [1, 2], f"S-tier chunks should be at positions [1, 2], got {s_tier_positions}"

    assert ranked_results[0]["s3_key"] == "s_tier_high_score", "Highest scoring S-tier should be first"

    print("\n✅ All tests passed! S-tier chunks are correctly ranked first.")


if __name__ == "__main__":
    test_s_tier_ranking()
