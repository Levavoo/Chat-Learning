export function resolveEmbeddingModelArn(
  region: string,
  override?: string,
): string {
  if (override) {
    return override;
  }
  return `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`;
}

export function resolveParsingModelArn(
  region: string,
  override?: string,
): string {
  if (override) {
    return override;
  }
  return `arn:aws:bedrock:${region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0`;
}
