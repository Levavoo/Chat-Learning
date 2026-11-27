"""Glossary module for prompt enrichment."""

import json
from dataclasses import dataclass
from pathlib import Path

from aws_lambda_powertools import Logger

logger = Logger(child=True)

_GLOSSARY_PATH = Path(__file__).parent / "data" / "glossary.json"
_glossary_cache: "list[GlossaryEntry] | None" = None


@dataclass
class GlossaryEntry:
    term: str
    definition: str


def load_glossary(path: str | None = None) -> list[GlossaryEntry]:
    """Load glossary from JSON, cached at module level."""
    global _glossary_cache
    if _glossary_cache is not None:
        return _glossary_cache

    glossary_path = Path(path) if path else _GLOSSARY_PATH
    try:
        with open(glossary_path, encoding="utf-8") as f:
            raw = json.load(f)
        _glossary_cache = [
            GlossaryEntry(term=e["term"], definition=e["definition"]) for e in raw if "term" in e and "definition" in e
        ]
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to load glossary", extra={"path": str(glossary_path), "error": str(exc)})
        return []

    return _glossary_cache


def build_glossary_prompt_context(entries: list[GlossaryEntry]) -> str:
    """Format all entries as [GLOSSAR-KONTEXT] block for system prompt injection."""
    lines = []
    for e in entries:
        lines.append(f"\u2022 {e.term}: {e.definition}")
    body = "\n".join(lines)
    return (
        "[GLOSSAR-KONTEXT]\n"
        "Du verfügst über ein verbindliches Glossar der Deutschen Rentenversicherung. "
        "Diese Definitionen haben Vorrang vor allgemeinen Informationen aus der Wissensbasis. "
        "Wenn die Nutzeranfrage einen Glossarbegriff betrifft, verwende primär die Glossar-Definition "
        "als Grundlage deiner Antwort. "
        "Wenn die Nutzeranfrage eine Fehlannahme zu einem dieser Begriffe enthält, "
        "stelle dies sachlich und freundlich richtig.\n\n"
        f"{body}\n"
        "[/GLOSSAR-KONTEXT]"
    )
