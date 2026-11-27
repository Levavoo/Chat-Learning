"""pydantic-ai compatible tool wrappers with type validation."""

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from aws_lambda_powertools import Logger, Tracer
from opentelemetry import trace
from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from backend_orchestrator.config import get_config
from backend_orchestrator.observability import set_content_attribute
from backend_orchestrator.tools.kb_retrieval import AgentDeps, Domain, search_knowledge_base

logger = Logger(child=True)
tracer = Tracer()

_BROCHURE_ID_RE = re.compile(r"^[A-Z]{1,2}\d{2,4}$")
_SHORT_URL_BASE = "https://www.deutsche-rentenversicherung.de"


def _derive_short_brochure_url(brochure_id: str) -> str | None:
    """Derive the short-form public URL for a brochure ID, or None if not derivable."""
    if not _BROCHURE_ID_RE.match(brochure_id):
        return None
    return f"{_SHORT_URL_BASE}/{brochure_id}"


def _safe_eval(expression: str) -> float | int:  # noqa: C901
    """Safely evaluate a mathematical expression without using eval().

    Supports: +, -, *, /, %, parentheses, and decimal numbers.

    Args:
        expression: Mathematical expression string

    Returns:
        Calculated result

    Raises:
        ValueError: If expression is invalid or contains unsupported operations

    """
    import re

    tokens = re.findall(r"\d+\.?\d*|[+\-*/()%]", expression.replace(" ", ""))
    pos = 0

    def parse_expression() -> float:
        nonlocal pos
        result = parse_term()
        while pos < len(tokens) and tokens[pos] in ("+", "-"):
            op = tokens[pos]
            pos += 1
            right = parse_term()
            result = result + right if op == "+" else result - right
        return result

    def parse_term() -> float:
        nonlocal pos
        result = parse_factor()
        while pos < len(tokens) and tokens[pos] in ("*", "/", "%"):
            op = tokens[pos]
            pos += 1
            right = parse_factor()
            if op == "*":
                result = result * right
            elif op == "/":
                if right == 0:
                    raise ValueError("Division by zero")
                result = result / right
            else:
                if right == 0:
                    raise ValueError("Modulo by zero")
                result = result % right
        return result

    def parse_factor() -> float:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Unexpected end of expression")

        token = tokens[pos]
        if token == "(":  # noqa: S105
            pos += 1
            result = parse_expression()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError("Missing closing parenthesis")
            pos += 1
            return result
        elif token == "-":  # noqa: S105
            pos += 1
            return -parse_factor()
        elif token == "+":  # noqa: S105
            pos += 1
            return parse_factor()
        else:
            pos += 1
            return float(token)

    result = parse_expression()
    if pos < len(tokens):
        raise ValueError(f"Unexpected token: {tokens[pos]}")
    return int(result) if result == int(result) else result


@tracer.capture_method
def calculator_pydantic(
    ctx: RunContext[AgentDeps],
    expression: Annotated[str, Field(description="Mathematical expression", pattern=r"^[0-9+\-*/()%. ]+$")],
) -> str:
    """Perform mathematical calculations with type validation."""
    logger.info("Tool called: calculator", extra={"expression": expression})
    try:
        result = _safe_eval(expression)
        logger.info("Tool completed: calculator", extra={"result": str(result)})
        return str(result)
    except Exception as e:
        logger.warning("Tool failed: calculator", extra={"error": str(e)})
        return f"Error calculating '{expression}': {e!s}"


@tracer.capture_method
def current_time_pydantic(ctx: RunContext[AgentDeps]) -> str:
    """Get current date and time in ISO 8601 format."""
    logger.info("Tool called: current_time")
    result = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    logger.info("Tool completed: current_time", extra={"result": result})
    return result


@tracer.capture_method
def get_drv_contact_info_pydantic(
    ctx: RunContext[AgentDeps],
    contact_type: Annotated[str, Field(description="Type: phone, email, address, hotline, website")],
) -> str:
    """Get DRV-Bund contact information."""
    logger.info("Tool called: get_drv_contact_info", extra={"contact_type": contact_type})
    contact_info = {
        "phone": (
            "DRV-Bund Service Hotline: 0800 1000 4800\n"
            "Montag bis Donnerstag: 8:00 - 18:00 Uhr\n"
            "Freitag: 8:00 - 16:00 Uhr"
        ),
        "email": (
            "Allgemeine Anfragen: info@drv-bund.de\n"
            "Presseanfragen: presse@drv-bund.de\n"
            "Technische Fragen: webmaster@drv-bund.de"
        ),
        "address": ("Deutsche Rentenversicherung Bund\nRuhrstraße 2\n10711 Berlin\nDeutschland"),
        "hotline": (
            "Rentenversicherung Hotline: 0800 1000 4800 (kostenlos)\n"
            "Service-Zentrale: 030 865-0 (Ortsnetzgebühr)\n"
            "Hörbehinderte: 0800 1000 4801 (kostenlos)"
        ),
        "website": (
            "Hauptseite: www.drv-bund.de\n"
            "Online-Service: www.drv-bund.de/online-dienste\n"
            "Formulare: www.drv-bund.de/formulare"
        ),
    }

    contact_type_lower = contact_type.lower()
    if contact_type_lower in contact_info:
        logger.info("Tool completed: get_drv_contact_info", extra={"found": True})
        return contact_info[contact_type_lower]

    logger.info("Tool completed: get_drv_contact_info", extra={"found": False})
    return (
        "DRV-Bund Kontaktinformationen:\n"
        "Service Hotline: 0800 1000 4800 (Mo-Do 8-18, Fr 8-16 Uhr)\n"
        "Website: www.drv-bund.de\n"
        "Adresse: Ruhrstraße 2, 10711 Berlin\n"
        "Email: info@drv-bund.de"
    )


def _make_search_kb_tool(rephrase: bool = True):
    """Create search_knowledge_base pydantic tool with or without rephrase instruction."""
    query_desc = (
        "Rephrase the user's question as a concise, keyword-focused retrieval query optimized for semantic search. "
        "Use official DRV terminology from the glossary context when available."
        if rephrase
        else "Search query to find relevant information in the knowledge base."
    )
    # Retrieval has no access to the chat history, so the query must stand on its own.
    query_desc += (
        " For follow-up questions, make the query self-contained: resolve references to earlier turns"
        " (pronouns, 'und dabei?', 'was ist mit X?') by inserting the concrete topic from the"
        " conversation so far, so the query is understandable without the chat history."
    )

    @tracer.capture_method(capture_response=False)
    def search_knowledge_base_pydantic(
        ctx: RunContext[AgentDeps],
        query: Annotated[str, Field(description=query_desc, min_length=3)],
        domain: Annotated[
            Domain,
            Field(
                description=(
                    "Domäne der Frage — wähle den passendsten Wert:\n"
                    "rente — Renten, Rentenantragstellung, Hinterbliebenenrente, Erwerbsminderungsrente, Grundrente, Rentensplitting, Knappschaftsrente, Steuer auf Renten, Krankenversicherung der Rentner\n"
                    "reha — Medizinische Rehabilitation, Berufliche Rehabilitation, Reha nach Tumor, Entwöhnungsbehandlung, Reha für Kinder/Jugendliche\n"
                    "versicherung — Kontenklärung, freiwillige Versicherung, Pflegepersonen, Minijobs, Selbständigkeit, Versorgungsausgleich, Beitragserstattung, Kindererziehung, Arbeitgeber, Studierende, Arbeitslose, Aussiedler, Berufsstarter\n"
                    "sonstiges — betriebliche Altersvorsorge, private Altersvorsorge, ausländische Arbeitnehmer, Grundsicherung, Online-Services, Wertguthaben-Übertragung\n"
                    "themenfremd — Frage hat nichts mit DRV-Themen zu tun\n"
                    "mehrdeutig — Frage umfasst mehrere Domänen gleichwertig"
                )
            ),
        ],
    ) -> str:
        """Search knowledge base with query and domain classification."""
        ctx.deps.kb_call_count += 1

        span = trace.get_current_span()
        set_content_attribute(span, "retrieval.query", query)
        span.set_attribute("retrieval.domain", str(domain))

        logger.info(
            "Tool called: search_knowledge_base",
            extra={"query": query[:50], "domain": str(domain), "call_num": ctx.deps.kb_call_count},
        )

        if domain == Domain.MEHRDEUTIG:
            return (
                "Die Nutzerfrage ist zu ungenau formuliert. Bitte stelle dem Nutzer eine Rückfrage "
                "die darauf abzielt, was er genau möchte und in welche Kategorie (Reha, Rente, Versicherung) die Frage fallen soll."
            )

        ctx.deps.last_retrieval_query = query
        result = search_knowledge_base(
            query, ctx.deps.sources, ctx.deps.kb_call_count, str(domain), ctx.deps.original_question
        )
        logger.info("Tool completed: search_knowledge_base", extra={"result_len": len(result)})

        if result.startswith("Error searching"):
            raise ModelRetry(
                "Knowledge base Suche fehlgeschlagen. Versuche es erneut mit einer angepassten Formulierung der Suchanfrage."
            )

        return result

    return search_knowledge_base_pydantic


def _parse_agent_search_meta(result_text: str) -> list[dict]:
    """Parse META lines from search agent output into retrieval context dicts."""
    sources = []
    for match in re.finditer(r"^META\|(\d+)\|([^|]+)\|([^|]+)\|([^|]*)\|([^|]*)\|(.+)$", result_text, re.MULTILINE):
        idx, doc_id, title, edition, published, section = match.groups()
        sources.append({
            "content": "",
            "contentType": "text",
            "rank": int(idx),
            "title": title,
            "documentId": doc_id,
            "sourceName": title,
            "sourceIndex": int(idx),
            "brochureUrl": _derive_short_brochure_url(doc_id) or "",
            "brochureNumber": doc_id,
            "publishingDate": published,
            "edition": edition,
            "sectionTitle": section,
        })
    return sources


def _make_agent_search_tool():
    """Create agent-based document search tool."""
    from backend_orchestrator.agents.agent import create_search_agent
    from backend_orchestrator.tools.agent_search import fetched_docs_context

    @tracer.capture_method
    def agent_search_pydantic(
        ctx: RunContext[AgentDeps],
        query: Annotated[str, Field(description="Suchanfrage des Benutzers", min_length=3)],
    ) -> str:
        """Search documents using the document search agent."""
        span = trace.get_current_span()
        set_content_attribute(span, "retrieval.query", query)

        logger.info("Tool called: agent_search", extra={"query": query[:50]})
        fetched_docs_context.set([])
        agent = create_search_agent()
        result = agent.run_sync(query)
        result_text = str(result.output)

        sources = _parse_agent_search_meta(result_text)

        # Fallback: build sources from actually fetched documents if META parsing failed.
        if not sources:
            fetched_docs = fetched_docs_context.get() or []
            for i, doc in enumerate(fetched_docs, 1):
                sources.append({
                    "content": doc.get("content", ""),
                    "contentType": "text",
                    "rank": i,
                    "title": doc["title"],
                    "documentId": doc["doc_id"],
                    "sourceName": doc["title"],
                    "sourceIndex": i,
                    "brochureUrl": doc.get("brochure_url_short") or _derive_short_brochure_url(doc["doc_id"]) or "",
                    "brochureNumber": doc["doc_id"],
                    "publishingDate": doc.get("published", ""),
                    "edition": doc.get("edition", ""),
                    "sectionTitle": "",
                })
            logger.info("Built sources from fetched docs (META fallback)", extra={"count": len(sources)})

        if sources:
            for source in sources:
                pattern = rf"\[Source {source['rank']}:[^\]]*\]\n(.*?)(?=\[Source |\nMETA\||$)"
                content_match = re.search(pattern, result_text, re.DOTALL)
                if content_match:
                    source["content"] = content_match.group(1).strip()

            ctx.deps.sources.extend(sources)

        logger.info("Tool completed: agent_search", extra={"result_len": len(result_text), "sources": len(sources)})
        return result_text

    return agent_search_pydantic


@tracer.capture_method
def get_drv_online_services_pydantic(
    ctx: RunContext[AgentDeps],
    topic: Annotated[str, Field(description="Thema oder Stichwort für die Suche nach Online-Services")],
) -> str:
    """Get relevant DRV-Bund online services based on topic/keyword.

    Use this tool when the user mentions topics like applications, pension
    calculations, address changes, appeals, or needs digital services from
    the DRV.
    """
    logger.info("Tool called: get_drv_online_services", extra={"topic": topic})

    online_services = {
        "kundenportal": {
            "name": "Mein Kundenportal",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Kundenportal/kundenportal-node.html",
            "description": "Der zentrale, sichere Zugang zu allen persönlichen digitalen Services der Rentenversicherung.",
            "keywords": ["kundenportal", "portal", "login", "anmelden", "zugang", "konto", "digital", "online"],
        },
        "antrag": {
            "name": "Antrag stellen",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/antrag_stellen.html",
            "description": "Ermöglicht das Stellen eines neuen Antrags (z.B. auf Rente oder Reha) oder das Fortsetzen eines gespeicherten Antrags.",
            "keywords": [
                "antrag",
                "beantragen",
                "rente",
                "reha",
                "rehabilitation",
                "erwerbsminderung",
                "altersrente",
                "antragstellung",
            ],
        },
        "mitteilungen": {
            "name": "Mitteilungen an uns mit Zugangscode",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/mitteilungen_mit_zugangscode.html",
            "description": "Antworten auf Schreiben der Rentenversicherung können hier direkt per Zugangscode übermittelt werden.",
            "keywords": ["mitteilung", "zugangscode", "antwort", "schreiben", "nachricht", "dokument"],
        },
        "rechner": {
            "name": "Online-Rechner",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/Online-Rechner/online_rechner.html",
            "description": "Verschiedene Tools zur Berechnung des Rentenbeginns, der Rentenhöhe oder des Barwerts.",
            "keywords": [
                "rechner",
                "berechnung",
                "rentenbeginn",
                "rentenhöhe",
                "barwert",
                "rentenrechner",
                "berechnen",
                "kalkulation",
            ],
        },
        "informationen": {
            "name": "Informationen anfordern",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/informationen_anfordern.html",
            "description": "Anforderung von Dokumenten wie dem Versicherungsverlauf, dem Versicherungsnummernachweis oder einer Steuerbescheinigung.",
            "keywords": [
                "versicherungsverlauf",
                "versicherungsnummer",
                "nachweis",
                "steuerbescheinigung",
                "dokument",
                "anfordern",
                "auskunft",
                "verlauf",
            ],
        },
        "daten_aendern": {
            "name": "Persönliche Daten ändern",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/Persoenliche-Daten-aendern/persoenliche_daten_aendern.html",
            "description": "Schnelle Online-Änderung von Bankverbindung oder Adresse.",
            "keywords": [
                "adresse",
                "bankverbindung",
                "ändern",
                "änderung",
                "daten",
                "persönlich",
                "iban",
                "umzug",
                "bank",
            ],
        },
        "kommunikation": {
            "name": "Kommunikation mit uns",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/kommunikation_mit_uns.html",
            "description": "Zentrale Stelle zum Einreichen von Unterlagen, Nutzung des Kontaktformulars oder zur Suche von Ansprechpartnern.",
            "keywords": [
                "kontakt",
                "kontaktformular",
                "unterlagen",
                "einreichen",
                "kommunikation",
                "ansprechpartner",
                "frage",
            ],
        },
        "widerspruch": {
            "name": "Widerspruch gegen einen Bescheid online einlegen",
            "url": "https://www.deutsche-rentenversicherung.de/DRV/DE/Online-Services/Rechtsbehelfsbelehrung/widerspruch.html",
            "description": "Formular zur rechtssicheren Online-Einreichung eines Widerspruchs gegen einen Bescheid.",
            "keywords": ["widerspruch", "bescheid", "einspruch", "ablehnung", "rechtsbehelf", "rechtsmittel"],
        },
        "rentenuebersicht": {
            "name": "Digitale Rentenübersicht",
            "url": "https://www.rentenuebersicht.de/DE/01_startseite/home_node.html",
            "description": "Ein externes Portal, das eine Übersicht über gesetzliche, betriebliche und private Altersvorsorgeansprüche bietet.",
            "keywords": [
                "rentenübersicht",
                "übersicht",
                "altersvorsorge",
                "betrieblich",
                "privat",
                "gesetzlich",
                "anspruch",
                "ansprüche",
            ],
        },
    }

    topic_lower = topic.lower()
    matched_services = []

    for _, service in online_services.items():
        if any(keyword in topic_lower for keyword in service["keywords"]) or any(
            topic_lower in keyword for keyword in service["keywords"]
        ):
            matched_services.append(service)

    if matched_services:
        result_lines = ["Relevante Online-Services der Deutschen Rentenversicherung:\n"]
        for i, service in enumerate(matched_services, 1):
            result_lines.append(f"{i}. **{service['name']}**")
            result_lines.append(f"   {service['description']}")
            result_lines.append(f"   URL: {service['url']}\n")
        logger.info("Tool completed: get_drv_online_services", extra={"matches": len(matched_services)})
        return "\n".join(result_lines)

    result_lines = ["Alle Online-Services der Deutschen Rentenversicherung:\n"]
    for i, service in enumerate(online_services.values(), 1):
        result_lines.append(f"{i}. **{service['name']}**")
        result_lines.append(f"   {service['description']}")
        result_lines.append(f"   URL: {service['url']}\n")

    logger.info("Tool completed: get_drv_online_services", extra={"matches": "all"})
    return "\n".join(result_lines)


def get_pydantic_tools(rephrase: bool = True) -> list[Any]:
    """Get all pydantic-ai compatible tools.

    Args:
        rephrase: If True, the KB search tool instructs the LLM to rephrase the query.

    """
    app_config = get_config()
    search_tool = _make_agent_search_tool() if app_config.search_mode == "agent" else _make_search_kb_tool(rephrase)

    return [
        calculator_pydantic,
        current_time_pydantic,
        get_drv_contact_info_pydantic,
        get_drv_online_services_pydantic,
        search_tool,
    ]
