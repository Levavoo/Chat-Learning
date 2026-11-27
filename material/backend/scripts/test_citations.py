"""Smoke-test: verify the agent emits [N] citation markers before stripping.

Run:
    eval "$(aws configure export-credentials --profile digibro-eu-dev --format env)"
    export KNOWLEDGE_BASE_ID=FGMZGPLSL1
    export AWS_REGION=eu-central-1
    uv run python backend/scripts/test_citations.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from pydantic_ai.usage import UsageLimits

from backend_orchestrator.agents.agent import (
    AgentDeps,
    create_agent,
)
from backend_orchestrator.tools.kb_retrieval import AgentDeps  # noqa: F811

QUESTIONS = [
    "Ab wann kann ich in Rente gehen?",
    "Was ist die Grundrente und wer hat Anspruch darauf?",
    "Wie beantrage ich medizinische Rehabilitation?",
    "Wie funktioniert die freiwillige Versicherung in der Rentenversicherung?",
    "Was passiert mit meiner Rente wenn ich ins Ausland ziehe?",
]


def main() -> None:
    """Run the question set and print raw model output before citation normalization."""
    agent = create_agent()
    passed = 0

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n{'=' * 70}")
        print(f"[{i}/5] {question}")
        print("=" * 70)

        deps = AgentDeps()
        result = agent.run_sync(
            question,
            deps=deps,
            usage_limits=UsageLimits(request_limit=10),
        )

        raw = result.output
        print(f"\n📄 Raw AgentResponse.answer (before normalization):\n{raw.answer}")
        print(f"\n📌 cited_source_indices: {raw.cited_source_indices}")
        print(f"📚 sources collected:    {len(deps.sources)}")

        import re

        brackets = re.findall(r"\[\d+(?:,\s*\d+)*\]", raw.answer)
        if brackets:
            print(f"✅ Citations found: {brackets}")
            passed += 1
        else:
            print("❌ NO citation brackets in answer")

    print(f"\n{'=' * 70}")
    print(f"Result: {passed}/{len(QUESTIONS)} answers contained citation brackets")
    if passed == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
