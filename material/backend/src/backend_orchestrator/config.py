"""Configuration management using singleton pattern."""

import logging
import os
from typing import ClassVar

logger = logging.getLogger(__name__)


class Config:
    """Singleton configuration class for orchestrator settings."""

    _instance: ClassVar["Config | None"] = None

    def __new__(cls) -> "Config":
        """Ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize configuration from environment variables."""
        self.allowed_origin = os.environ.get("ALLOWED_ORIGIN", "https://example.com")
        self.cors_max_age = int(os.environ.get("CORS_MAX_AGE", "300"))

        self.max_message_length = int(os.environ.get("MAX_MESSAGE_LENGTH", "10000"))
        self.min_message_length = int(os.environ.get("MIN_MESSAGE_LENGTH", "1"))
        self.max_word_length = int(os.environ.get("MAX_WORD_LENGTH", "1000"))
        self.max_special_char_ratio = float(os.environ.get("MAX_SPECIAL_CHAR_RATIO", "0.5"))

        self.aws_region = os.environ.get("AWS_REGION", "eu-central-1")

        self.knowledge_base_id = os.environ.get("KNOWLEDGE_BASE_ID", "")
        self.bedrock_model_id = os.environ.get("BEDROCK_MODEL_ID", "openai.gpt-oss-120b-1:0")
        self.kb_retrieval_results = int(os.environ.get("KB_RETRIEVAL_RESULTS", "50"))
        self.bedrock_temperature = float(os.environ.get("BEDROCK_TEMPERATURE", "0.0"))
        self.bedrock_top_p = float(os.environ.get("BEDROCK_TOP_P", "1.0"))

        # Empty model ARN = reranker disabled.
        self.kb_reranker_model_arn = os.environ.get("KB_RERANKER_MODEL_ARN", "")
        self.kb_reranker_results = int(os.environ.get("KB_RERANKER_RESULTS", "30"))

        self.bedrock_guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
        self.bedrock_guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
        self.guardrail_agent_model_id = os.environ.get("GUARDRAIL_AGENT_MODEL_ID", "")

        self.hyde_enabled = os.environ.get("HYDE_ENABLED", "false").lower() == "true"
        self.hyde_model_id = os.environ.get("HYDE_MODEL_ID", "eu.amazon.nova-2-lite-v1:0") or self.bedrock_model_id

        self.bm25_index_bucket = os.environ.get("BM25_INDEX_BUCKET", "")
        self.bm25_index_key = os.environ.get("BM25_INDEX_KEY", "bm25_index/index.json")
        self.bm25_enabled = os.environ.get("BM25_ENABLED", "false").lower() == "true"
        self.bm25_weight = float(os.environ.get("BM25_WEIGHT", "1.0"))
        # Required atomic semantic + BM25 coordinate; deployments without it fall back to env-based config.
        self.retrieval_manifest_parameter = os.environ.get("RETRIEVAL_MANIFEST_PARAMETER", "")

        self.anchor_retrieval_enabled = os.environ.get("ANCHOR_RETRIEVAL_ENABLED", "true").lower() == "true"
        self.anchor_min_docs = int(os.environ.get("ANCHOR_MIN_DOCS", "3"))
        self.anchor_max_docs = int(os.environ.get("ANCHOR_MAX_DOCS", "8"))
        self.anchor_s_tier_guaranteed = os.environ.get("ANCHOR_S_TIER_GUARANTEED", "true").lower() == "true"
        self.anchor_chunks_per_doc = int(os.environ.get("ANCHOR_CHUNKS_PER_DOC", "6"))
        self.anchor_rare_term_boost = float(os.environ.get("ANCHOR_RARE_TERM_BOOST", "1.5"))

        # Supplementary brochure-scoped retrieve unioned into the candidate pool when curated keywords match.
        self.metadata_routing_enabled = os.environ.get("METADATA_ROUTING_ENABLED", "true").lower() == "true"
        self.metadata_routing_results = int(os.environ.get("METADATA_ROUTING_RESULTS", "15"))
        self.metadata_routing_min_matches = int(os.environ.get("METADATA_ROUTING_MIN_MATCHES", "1"))
        # 1 restores the strict "more matches than anyone else" rule without a deploy.
        self.metadata_routing_max_tied = int(os.environ.get("METADATA_ROUTING_MAX_TIED", "2"))

        # Collapse an extracted _table_NNN / _note_NNN subdocument into its parent chunk after fusion + rerank.
        self.content_dedup_enabled = os.environ.get("CONTENT_DEDUP_ENABLED", "true").lower() == "true"
        # Guard malformed env vars so Lambda cold-start doesn't brick.
        try:
            self.content_dedup_containment_min = float(os.environ.get("CONTENT_DEDUP_CONTAINMENT_MIN", "0.80"))
        except ValueError:
            logger.warning("Invalid CONTENT_DEDUP_CONTAINMENT_MIN env var; falling back to 0.80")
            self.content_dedup_containment_min = 0.80
        try:
            self.content_dedup_parent_context_min = float(os.environ.get("CONTENT_DEDUP_PARENT_CONTEXT_MIN", "0.50"))
        except ValueError:
            logger.warning("Invalid CONTENT_DEDUP_PARENT_CONTEXT_MIN env var; falling back to 0.50")
            self.content_dedup_parent_context_min = 0.50
        try:
            # max(1, …): a zero/negative shingle size would break the n-gram window loop.
            self.content_dedup_shingle_size = max(1, int(os.environ.get("CONTENT_DEDUP_SHINGLE_SIZE", "8")))
        except ValueError:
            logger.warning("Invalid CONTENT_DEDUP_SHINGLE_SIZE env var; falling back to 8")
            self.content_dedup_shingle_size = 8

        self.brochure_priority_file = os.environ.get("BROCHURE_PRIORITY_FILE", "data/brochure_priorities.json")

        self.langfuse_host = os.environ.get("LANGFUSE_HOST", "")
        self.langfuse_secret_name = os.environ.get("LANGFUSE_SECRET_NAME", "")
        # Opt-in content telemetry; gates both pydantic-ai instrumentation and manual OTel attributes.
        self.otel_include_content = os.environ.get("OTEL_INCLUDE_CONTENT", "false").lower() == "true"
        self.environment = os.environ.get("ENVIRONMENT", "unknown")
        self.review_id = os.environ.get("REVIEW_ID", "")
        self.langfuse_review_tag = os.environ.get("LANGFUSE_REVIEW_TAG", "")

        # Minimum 1; malformed env var falls back to 30 so Lambda cold-start doesn't brick.
        try:
            self.conversation_ttl_days = max(1, int(os.environ.get("CONVERSATION_TTL_DAYS", "30")))
        except ValueError:
            logger.warning("Invalid CONVERSATION_TTL_DAYS env var; falling back to 30")
            self.conversation_ttl_days = 30

        self.search_mode = os.environ.get("SEARCH_MODE", "rag")  # "rag" | "agent"
        self.agent_search_index_bucket = os.environ.get("AGENT_SEARCH_INDEX_BUCKET", "")
        self.agent_search_index_prefix = os.environ.get("AGENT_SEARCH_INDEX_PREFIX", "agent-search-index/")
        self.agent_search_model_id = os.environ.get("AGENT_SEARCH_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")

    @property
    def langfuse_environment(self) -> str:
        """Return 'review' when running in a review env, otherwise the configured environment."""
        return "review" if self.review_id else self.environment

    @classmethod
    def get_instance(cls) -> "Config":
        """Get the singleton instance."""
        return cls()


def get_config() -> Config:
    """Return the singleton config instance."""
    return Config.get_instance()
