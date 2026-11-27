# Frontend-Architektur

## Übersicht

Angular 19 SPA mit Chat-Interface für Renate, unter Verwendung von AWS Amplify für die Authentifizierung und dem DRV-Design-System für die Benutzeroberfläche. Unterstützt Mehrturn-Konversationen mit automatischer Session-Wiederherstellung.

## Architektur

```text
Browser des Benutzers
     ↓
┌──────────────────┐
│ Angular App      │
│ ┌──────────────┐ │
│ │ Komponenten  │ │
│ │ - Chatbot    │ │
│ │ - Chat-Panel │ │
│ │ - Feedback   │ │
│ └──────────────┘ │
│ ┌──────────────┐ │
│ │ Services     │ │
│ │ - Auth       │ │
│ │ - API-Proxy  │ │
│ │ - Chat-Msg   │ │
│ └──────────────┘ │
│ ┌──────────────┐ │
│ │ Guards       │ │
│ │ - Auth       │ │
│ │ - Disclaimer │ │
│ └──────────────┘ │
└──────────────────┘
     │      │
     │      ▼
     │  ┌──────────────┐
     │  │ Cognito      │
     │  │ (Auth)       │
     │  └──────────────┘
     ▼
┌──────────────────┐
│ API Gateway      │
│ + Backend        │
└──────────────────┘
```

## Hauptkomponenten

### Seiten

- **start-page**: Einstiegsseite mit Haftungsausschluss
- **login**: Authentifizierungsseite
- **chat-page**: Haupt-Chat-Oberfläche

### Komponenten

- **chatbot**: Haupt-Chat-UI mit Nachrichtenanzeige
- **chat-panel**: Nachrichteneingabe und Steuerelemente
- **feedback**: Bewertungs- und Feedback-Sammlung
- **renate-header**: Anwendungs-Header
- **related-documents-panel**: Dokumentenvorschläge

### Services

- **auth.service**: Amplify-Authentifizierung
- **bedrock-chat.service**: Backend-API-Aufrufe, History-Laden, Initialisierung
- **chat-message.service**: Nachrichten-Zustandsverwaltung
- **session.service**: Session-Persistenz, `hadExistingSession()` Flag

### Guards

- **auth.guard**: Routenschutz (erfordert Authentifizierung)
- **disclaimer.guard**: Prüfung der Haftungsausschluss-Akzeptanz

### Interceptors

- **auth.interceptor**: JWT-Token-Injektion

## Zustandsverwaltung

Verwendet Service-basierte Zustandsverwaltung (kein NgRx):

- Chat-Nachrichten im ChatMessageService
- Auth-Zustand im AuthService
- Haftungsausschluss-Zustand im DisclaimerService
- Session-ID im SessionService (localStorage)

## Mehrturn-Konversationen

### Session-Initialisierung

```typescript
// SessionService
hadExistingSession(): boolean  // True wenn Session bei Page Load existierte
createNewSession(): string     // Erstellt neue UUID, setzt Flag zurück
```

### History-Laden

```typescript
// BedrockChatService
async initialize(): Promise<void> {
  if (sessionService.hadExistingSession()) {
    const history = await loadConversationHistory(sessionId);
    if (history.length > 0) {
      this.chatMessages = history;
      return;
    }
  }
  await addWelcomeMessage();
}

loadConversationHistory(sessionId): Observable<ChatMessage[]>
```

### Initialisierungs-Flow

```text
Page Load
    → SessionService.initializeSession()
    → localStorage.getItem(session_id)
    → hadExistingSession = true/false
    → BedrockChatService.initialize()
    → IF hadExistingSession:
        → GET /api/chat/{session_id}/history
        → mapHistoryToMessages()
        → Display restored conversation
    → ELSE:
        → addWelcomeMessage()
```

### Loading State

```typescript
// ChatbotComponent
historyLoading = true; // Während History geladen wird
// Input disabled während historyLoading || isLoading
```

## Routing

```typescript
Routen:
  '' → start-page
  'login' → login (öffentlich)
  'chat' → chat-page (authGuard + disclaimerGuard)
```

## API-Kommunikation

HTTP-Aufrufe via HttpClient mit:

- Auth-Interceptor fügt JWT hinzu
- Fehlerbehandlung in Services
- Observable-basierte asynchrone Operationen

## UI-Framework

DRV-Design-System:

- Grid: 24-Spalten responsive
- Typografie: Barlow-Schriftart
- Farben: DRV-Markenfarben
- Komponenten: Individuelle Angular-Komponenten

## Sicherheit

- JWT-basierte Authentifizierung
- Route-Guards für Zugriffskontrolle
- Nur HTTPS-Kommunikation
- Session-ID in localStorage (nur UUID, keine PII)

## Performance

- Lazy Loading (zukünftige Erweiterung)
- OnPush Change-Detection-Strategie
- TrackBy-Funktionen in Schleifen
- AOT-Kompilierung in Produktion

Siehe [Frontend-Entwicklungshandbuch](./development-guide-frontend.md) für Details.
