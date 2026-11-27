# CDK-Architektur

## Übersicht

AWS CDK TypeScript-Infrastruktur, die alle Cloud-Ressourcen für die Chatbot-Anwendung definiert.

## Stack-Architektur

### Haupt-Stacks

1. **ChatbotStack**: Hauptanwendungs-Infrastruktur
2. **EtlKbStack**: ETL-Pipeline + Knowledge Base
3. **RenateStack**: Renate-spezifische Ressourcen

## Wichtige Konstrukte

### Auth-Konstrukt

- Cognito User Pool
- User Pool Client
- OIDC Identity Provider
- Pre-Signup Lambda-Trigger
- E-Mail-Domain-Validierung

### Frontend-Konstrukt

- S3-Bucket für statisches Hosting
- CloudFront-Distribution
- Route53 DNS-Einträge
- ACM-Zertifikat
- Deploy-Time-Build-Integration

### Lambda-Backend-Konstrukt

- Lambda-Funktionen (Python 3.12)
- Container-Image-Deployment
- IAM-Ausführungsrollen
- VPC-Konfiguration
- Umgebungsvariablen

### API-Gateway-Konstrukt

- REST-API
- CORS-Konfiguration
- Lambda-Integration
- Authorizer (Cognito)

### Knowledge-Base-Konstrukt

- Bedrock Knowledge Base
- OpenSearch Serverless Vektorspeicher
- S3-Datenquelle
- Embedding-Modell-Konfiguration
- IAM-Richtlinien

### Netzwerk-Konstrukt

- VPC mit öffentlichen/privaten Subnetzen
- NAT Gateway
- Security Groups
- VPC-Endpunkte

## Ressourcen-Factories

### IAM-Factory

- Standard-Rollenerstellung
- Managed Policy-Anhängung
- Least-Privilege-Richtlinien

### S3-Factory

- Bucket-Erstellung mit Verschlüsselung
- Lifecycle-Richtlinien
- Event-Benachrichtigungen
- CORS-Konfiguration

### Custom-Resource-Factory

- Lambda-gestützte Custom Resources
- HTTP-Seeder
- KB-Sync-Trigger
- S3-Bereinigung bei Stack-Löschung

## Design-Patterns

### L3-Konstrukte

- High-Level-Abstraktionen
- Kapseln Best Practices
- Wiederverwendbar über Stacks hinweg

### Aspect-Pattern

- CodeBuild-Logs-Aspect
- Sicherheits-Compliance (cdk-nag)
- Tagging-Aspect

### Factory-Pattern

- Standardisierte Ressourcenerstellung
- Konsistente Konfiguration
- Reduzierter Boilerplate-Code

## Deployment-Pipeline

```text
Quelle (Git)
    ↓
Build
    ↓
CDK Synth
    ↓
CloudFormation
    ↓
AWS-Ressourcen
```

## Konfigurationsverwaltung

### Kontextvariablen

- Umgebung (dev, prod)
- Domain-Namen
- Feature-Flags

### Parameter-Validierung

- Zod-Schemas
- Laufzeit-Validierung
- Typsichere Konfiguration

## Sicherheit

- Verschlüsselung im Ruhezustand (S3, RDS)
- TLS während der Übertragung
- IAM Least Privilege
- cdk-nag Compliance-Prüfungen
- Secret-Rotation

Siehe [CDK-Entwicklungshandbuch](./development-guide-cdk.md) für Details.
