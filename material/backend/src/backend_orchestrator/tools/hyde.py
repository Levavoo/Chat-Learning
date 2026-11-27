"""HyDE (Hypothetical Document Embeddings) for improved RAG retrieval."""

import boto3
from aws_lambda_powertools import Logger, Tracer

logger = Logger(child=True)
tracer = Tracer()

_HYDE_SYSTEM_PROMPT = (
    "Du bist ein Experte für die Deutsche Rentenversicherung (DRV). "
    "Generiere einen hypothetischen Textabschnitt aus einem offiziellen DRV-Dokument, "
    "der die gestellte Frage beantwortet. "
    "Schreibe nur den Textabschnitt selbst, ohne Einleitung oder Erklärung."
)

_bedrock_runtime_client = None


def _get_bedrock_runtime_client(region: str):
    """Get or create cached bedrock-runtime client."""
    global _bedrock_runtime_client
    if _bedrock_runtime_client is None:
        _bedrock_runtime_client = boto3.client("bedrock-runtime", region_name=region)
    return _bedrock_runtime_client


@tracer.capture_method
def generate_hypothetical_document(query: str, model_id: str, region: str) -> str:
    """Generate a hypothetical DRV passage for HyDE retrieval. Falls back to the raw query on failure."""
    try:
        client = _get_bedrock_runtime_client(region)
        logger.info("HyDE: generating hypothetical document", extra={"query": query[:50], "model_id": model_id})

        response = client.converse(
            modelId=model_id,
            system=[{"text": _HYDE_SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": query}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0.5},
        )

        content = response.get("output", {}).get("message", {}).get("content", [])
        hypothetical_doc = next((block["text"] for block in content if "text" in block), "").strip()

        if not hypothetical_doc:
            logger.warning("HyDE: empty response, falling back to original query")
            return query
        else:
            logger.info("HyDE: hypothetical document generated", extra={"doc_len": len(hypothetical_doc)})
            return hypothetical_doc

    except Exception:
        logger.exception("HyDE: generation failed, falling back to original query")
        return query
