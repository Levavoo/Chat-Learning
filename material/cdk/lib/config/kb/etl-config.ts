/** Drives the DITA/XML → chunked Markdown pre-processing pipeline for Bedrock ingestion. */
export interface EtlConfig {
  lambdaTimeoutSeconds: number;
  lambdaMemorySizeMb: number;
  batchSize: number;
  batchWindowSeconds: number;
  visibilityTimeoutSeconds: number;
  messageRetentionDays: number;
  maxReceiveCount: number;
  /**
   * enabled=true inserts an intermediate bucket + Chunking Lambda between
   * transform and ingestion. CHUNK_MARKDOWN handles chunking either way;
   * the separate Lambda is for extra processing. config.yaml must then route .md files.
   */
  chunking?: {
    enabled: boolean;
  };
  contextualGrounding?: {
    /** @default true */
    enabled: boolean;
    /** @default eu.amazon.nova-pro-v1:0 */
    modelId: string;
  };
  /** LLM-based enrichment: section_title, keywords, colloquial_terms. */
  enrichment?: {
    /** @default false */
    enabled: boolean;
    /** @default eu.amazon.nova-lite-v1:0 */
    modelId: string;
  };
}
