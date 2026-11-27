# Backend-Architektur

## Übersicht

Das Backend besteht aus Lambda-basierten Services, die in AWS bereitgestellt werden und API-Orchestrierung, KI-Chatbot-Funktionalität und Dokumentenverarbeitung bieten.

## High-Level-Architektur

```text
┌─────────────────────────────────────────────────────────────┐
│                     Backend-Services                        │
│                                                             │
│  ┌────────────────────────────────────────────────────┐     │
│  │ Backend Orchestrator (API Gateway + Lambda)        │     │
│  │ ┌─────────────────────────────────────────────────┐│     │
│  │ │  Controller Layer (HTTP Request/Response)      ││      │
│  │ └───────────────────────┬─────────────────────────┘│     │
│  │                         │                          │     │
│  │ ┌───────────────────────▼─────────────────────────┐│     │
│  │ │  Service Layer (Geschäftslogik, Validierung)   ││      │
│  │ └───────────────────────┬─────────────────────────┘│     │
│  │                         │                          │     │
│  │ ┌───────────────────────▼─────────────────────────┐│     │
│  │ │  PydanticAgent (pydantic-ai Framework)         ││      │
│  │ │  - BedrockConverseModel (Nova Pro)             ││      │
│  │ │  - pydantic-ai Tools                           ││      │
│  │ └───────────────────────┬─────────────────────────┘│     │
│  └─────────────────────────┼──────────────────────────      │
│                            │                                │
│                            ▼                                │
│  ┌────────────────────────────────────────────────────┐     │
│  │              AWS Bedrock Services                  │     │
│  │  - Nova Pro (LLM via Converse API)                 │     │
│  │  - Knowledge Base (Vektorsuche)                    │     │
│  └────────────────────────────────────────────────────┘     │
│                                                             │
│  ┌────────────────────┐    ┌──────────────────────────┐     │
│  │   ETL-Pipeline     │    │    Auth Handler          │     │
│  │  (S3-getriggert)   │    │  (Cognito Trigger)       │     │
│  └────────────────────┘    └──────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Komponenten

### 1. Backend Orchestrator

**Zweck:** Haupt-API-Einstiegspunkt mit MVC-Architektur.

**Speicherort:** `backend/src/backend_orchestrator/`

**Laufzeit:** AWS Lambda (Python 3.12)

**Struktur:**

```text
backend_orchestrator/
├── orchestrator.py          # Lambda Handler, APIGatewayRestResolver
├── controllers/
│   └── chat_controller.py   # HTTP Request/Response Handling
├── services/
│   └── chat_service.py      # Geschäftslogik, Agent-Aufruf
├── repositories/
│   └── conversation.py      # DynamoDB Konversationsspeicher
├── agents/
│   ├── base.py              # AgentInterface (abstrakt)
│   ├── factory.py           # Agent-Factory
│   └── agent.py             # pydantic-ai Agent mit message_history
├── tools/
│   ├── pydantic_tools.py    # pydantic-ai kompatible Tools
│   ├── kb_retrieval.py      # Knowledge Base Suche (RAG-Modus)
│   └── agent_search.py      # Agent-basierte Dokumentensuche (Agent-Modus)
├── utils/
│   └── history_converter.py # Konvertierung zu ModelMessage
├── prompts.py               # Renate System-Prompt
├── config.py                # Konfiguration
├── validation.py            # Eingabevalidierung
└── response_parser.py       # Response-Parsing
```

**MVC-Pattern:**

- **Controller**: Empfängt HTTP-Requests, delegiert an Service
- **Service**: Enthält Geschäftslogik, ruft Agent auf
- **Agent**: Führt LLM-Interaktion mit Tools durch

**Request-Flow:**

```text
API Gateway
    → Lambda Handler (orchestrator.py)
    → ChatController (HTTP-Handling)
    → ChatService (Validierung, History-Laden)
    → Bedrock Guardrail (Hard Security: Hate, PII, Prompt Attacks)
    → Guardrail Agent / Nova Lite (Nuancierte Klassifikation)
        → BLOCK_STANDARD_1/2 → Standardantwort zurück
        → CLARIFY → Rückfrage zurück
        → ALLOW / ALLOW_WITH_CORRECTION → weiter
    → ConversationStore.get_history()
    → HistoryConverter.items_to_messages()
    → PydanticAgent (pydantic-ai mit message_history)
    → Bedrock Converse API
    → ConversationStore.store()
    → Response
```

### 2. PydanticAgent (Renate)

**Zweck:** KI-gestützter Chatbot mit pydantic-ai Framework und Mehrturn-Support.

**Speicherort:** `backend/src/backend_orchestrator/agents/`

**Framework:** pydantic-ai mit Bedrock Converse API

**Hauptkomponenten:**

- **PydanticAgent**: Agent-Wrapper mit `AgentInterface`
- **BedrockConverseModel**: AWS Bedrock Model-Integration
- **AgentResponse**: Typisierte Pydantic-Antwort
- **pydantic-ai Tools**: Typsichere Tool-Funktionen
- **message_history**: Konversationskontext für Mehrturn

**Architektur:**

```text
Benutzeranfrage + message_history → PydanticAgent
                                        ↓
                                BedrockConverseModel
                                        ↓
                                    Tool-Auswahl
                                        ↓
        ┌───────────────┬───────────────┼───────────────┬───────────────┐
        ▼               ▼               ▼               ▼               ▼
  Dokumentensuche   Rechner       Kontaktinfo    Online-Services    Uhrzeit
  (search_tool)   (calculator)   (get_drv_info) (get_drv_online)  (current_time)
        │               │               │               │               │
        └───────────────┴───────────────┼───────────────┴───────────────┘
                                        ▼
                                    Antwort
```

**Suchmodus (`SEARCH_MODE`):**

Das Such-Tool wird über die Umgebungsvariable `SEARCH_MODE` gesteuert:

- `rag` (Standard): Embedding-basierte Suche über Bedrock Knowledge Base (`kb_retrieval.py`)
- `agent`: Agent-basierte Dokumentensuche mit dediziertem Such-Agent (`agent_search.py`)

```text
Agent-Modus Ablauf:

Chatbot Agent → search_tool → Document Search Agent
                                    ↓
                              1. read_index (Index laden)
                                    ↓
                              2. fetch_document (1-3 Dokumente)
                                    ↓
                              3. Relevante Abschnitte auswählen
                                    ↓
                              Verifizierte Abschnitte + Quellenmetadaten
                                    ↓
                              ← zurück an Chatbot Agent → Antwort
```

**Tool-Ausführungsablauf:**

1. Benutzer sendet Anfrage
2. Service validiert Eingabe
3. **Service lädt Konversationshistorie aus DynamoDB**
4. **HistoryConverter wandelt Items → ModelMessage[]**
5. Agent analysiert Anfrage mit LLM (inkl. History-Kontext)
6. Agent wählt passende Tools
7. Tools werden ausgeführt (mit pydantic Validierung)
8. Agent synthetisiert finale Antwort
9. **Service speichert Austausch in DynamoDB**
10. Response wird an Benutzer zurückgegeben

### 2b. Konversationsspeicher (Repository)

**Zweck:** Persistenz und Abruf von Konversationshistorie.

**Speicherort:** `backend/src/backend_orchestrator/repositories/conversation.py`

**Hauptmethoden:**

- `store(item)`: Speichert ConversationItem in DynamoDB
- `get_history(session_id, limit)`: Lädt letzte N Austausche
- `update_feedback(session_id, message_id, feedback)`: Aktualisiert Feedback

**DynamoDB-Schema:**

```text
PK: session_id (String)
SK: message_id (String, UUID-Format)
Attribute: message, response_text, sources, created_at, feedback
```

### 2c. History Converter

**Zweck:** Konvertierung von ConversationItems zu pydantic-ai ModelMessage.

**Speicherort:** `backend/src/backend_orchestrator/utils/history_converter.py`

```python
def items_to_messages(items: list[ConversationItem]) -> list[ModelMessage]:
    """Konvertiert ConversationItems zu pydantic-ai ModelMessage-Liste."""
    messages = []
    for item in items[-MAX_HISTORY_PAIRS:]:
        messages.append(ModelRequest(parts=[UserPromptPart(content=item.message)]))
        messages.append(ModelResponse(parts=[TextPart(content=item.response_text)]))
    return messages
```

**Token-Budget:** MAX_HISTORY_PAIRS=20 (~10k Tokens)

### 3. ETL-Pipeline

**Zweck:** Dokumente für die Knowledge-Base-Ingestion verarbeiten.

**Speicherort:** `backend/src/etl/`

**Laufzeit:** AWS Lambda (Python 3.12), S3-Event-getriggert

**Pipeline-Komponenten:**

- **Ingest**: Aus S3-Bucket lesen
- **Transform**: Transformationskette anwenden
  - DITA XML → Markdown
  - PDF → Markdown
  - HTML → Markdown
  - Chunking für Vektorspeicher
- **Output**: In S3-Output-Bucket schreiben

### 4. Auth Handler

**Zweck:** Cognito Pre-Signup-Trigger für E-Mail-Domain-Validierung.

**Speicherort:** `backend/src/auth_handler/`

**Funktionalität:**

- E-Mail-Domain gegen Allowlist validieren
- Benutzer von erlaubten Domains automatisch bestätigen

## Datenfluss

### Chat-Request-Flow (mit Mehrturn)

```text
1. Benutzer sendet Nachricht vom Frontend
2. API Gateway empfängt Request
3. Cognito Authorizer validiert JWT-Token
4. Backend Orchestrator Lambda wird aufgerufen
5. ChatController extrahiert Request-Daten
6. ChatService validiert Eingabe
7. ChatService lädt Historie via ConversationStore.get_history()
8. HistoryConverter wandelt Items → ModelMessage[]
9. ChatService ruft PydanticAgent mit message_history auf
10. Agent führt LLM via Bedrock Converse API aus (mit Kontext)
11. Agent kann Knowledge-Base-Tool aufrufen
12. Bedrock KB gibt relevante Dokumente zurück
13. Agent synthetisiert Antwort mit Quellenangaben
14. ChatService speichert Austausch in DynamoDB
15. Response wird über API Gateway zurückgegeben
```

### History-Retrieval-Flow

```text
1. Frontend sendet GET /api/chat/{session_id}/history
2. API Gateway validiert JWT-Token
3. ChatController.handle_history_request() aufgerufen
4. ConversationStore.get_history(session_id, limit)
5. Items werden zu HistoryMessage[] konvertiert
6. HistoryResponse wird zurückgegeben
```

## Technologie-Stack

### Sprachen & Frameworks

- **Python:** 3.12+
- **pydantic-ai:** Agent-Framework mit Typsicherheit
- **Pydantic:** Datenvalidierung und Modelle
- **boto3:** AWS SDK
- **AWS Lambda Powertools:** Logging, Tracing, Metrics

### AWS-Services

- **Lambda:** Serverloses Computing
- **Bedrock:** KI-Foundation-Modelle (Converse API)
- **Bedrock Knowledge Bases:** Vektorsuche
- **S3:** Objektspeicher
- **API Gateway:** REST-API
- **Cognito:** Authentifizierung

### Entwicklungswerkzeuge

- **uv:** Paketmanager
- **pytest:** Test-Framework
- **ruff:** Linting & Formatierung
- **ty:** Typprüfung

## Design-Patterns

### 1. MVC-Pattern

Backend Orchestrator verwendet Model-View-Controller:

- **Controller**: HTTP-Schicht (Request/Response)
- **Service**: Geschäftslogik (Validierung, Orchestrierung)
- **Model/Agent**: Datenverarbeitung (LLM, Tools)

### 2. Dependency Injection

```python
# orchestrator.py
chat_service = ChatService()
chat_controller = ChatController(chat_service)
```

### 3. Factory-Pattern

Agent-Erstellung über Factory:

```python
agent = create_agent(model_id, system_prompt, config, region)
```

### 4. Strategy-Pattern

`AgentInterface` ermöglicht austauschbare Agent-Implementierungen:

```python
class AgentInterface(ABC):
    @abstractmethod
    def run(self, message: str, context: dict) -> dict: ...

    @abstractmethod
    async def run_async(self, message: str, context: dict) -> dict: ...
```

### 5. Context Variable Pattern

Für Request-scoped State (z.B. abgerufene Dokumente):

```python
from contextvars import ContextVar
retrieval_context: ContextVar[list] = ContextVar("retrieval_context")
```

## Sicherheitsarchitektur

### Authentifizierung & Autorisierung

- Cognito JWT-Tokens
- API Gateway Cognito Authorizer
- IAM-rollenbasierter Zugriff

### Eingabevalidierung

```python
# validation.py
def validate_message_length(message: str) -> tuple[bool, str]: ...
def contains_suspicious_content(message: str) -> bool: ...
```

### Zweistufige Guardrail-Architektur

Nutzereingaben durchlaufen zwei Guardrail-Schichten **vor** der RAG-Retrieval:

```text
Nutzeranfrage
    ↓
[1] Bedrock Guardrail (Hard Security)
    → Hassrede, Gewalt, PII, Prompt-Angriffe
    → Fail-closed: bei Blockierung → Standardantwort 1
    ↓
[2] Guardrail Agent (Nova Lite)
    → Nuancierte Klassifikation in 5 Kategorien
    → Fail-closed (außer bei Throttling/Timeout → fail-open)
    ↓
[3] Haupt-Chatbot (RAG + LLM)
```

**Kategorien des Guardrail Agent:**

| Kategorie             | Antwort                            |
| --------------------- | ---------------------------------- |
| ALLOW                 | Weiterleitung an Chatbot           |
| ALLOW_WITH_CORRECTION | Weiterleitung mit Korrekturhinweis |
| CLARIFY               | Rückfrage an Nutzer                |
| BLOCK_STANDARD_1      | Standardantwort 1 (Off-Topic)      |
| BLOCK_STANDARD_2      | Standardantwort 2 (Servicetelefon) |

**Einheitliche Blockierungsantwort:** Beide Schichten verwenden Standardantwort 1 bei Blockierung (keine separate Bedrock-Meldung). Dies sorgt für eine konsistente Nutzererfahrung.

**Speicherort:** `backend/src/backend_orchestrator/validators/`

### Datenschutz

- Keine PII in Logs
- Secrets in AWS Secrets Manager

## Monitoring & Observierbarkeit

### Logging (AWS Lambda Powertools)

```python
from aws_lambda_powertools import Logger
logger = Logger()

@logger.inject_lambda_context
def lambda_handler(event, context): ...
```

### Tracing (AWS X-Ray)

```python
from aws_lambda_powertools import Tracer
tracer = Tracer()

@tracer.capture_method
def chat_handler(): ...
```

## Performance-Metriken

### Ziel-SLAs

- API-Antwortzeit: <2s (p95)
- Agent-Antwortzeit: <5s (p95)
- Knowledge-Base-Abfrage: <500ms

## Verwandte Dokumentation

- [Backend-Entwicklungshandbuch](./development-guide-backend.md)
- [Agent-Konfigurationsanleitung](./agent-configuration-guide.md)
- [API-Verträge](./api-contracts.md)
- [Datenmodelle](./data-models.md)
