import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  ResolvedConfiguration,
  EmbeddingConfig,
  VectorConfig,
  CleanupConfig,
} from '../interfaces/common';

import { resolveEmbeddingModelArn } from './embedding-models';

export interface KnowledgeBaseConfigurationProps {
  readonly embeddingModel?: string;
  readonly vectorDimension?: number;
  readonly embeddingDataType?: 'FLOAT32' | 'BINARY';
  readonly distanceMetric?: 'cosine' | 'euclidean';
  readonly dataType?: 'float32';
  readonly useFoundationParsing?: boolean;
  readonly inclusionPrefixes?: string[];
  readonly parsingPromptText?: string;
  readonly namePrefix?: string;
  readonly cleanupEnabled?: boolean;
  readonly cleanupTimeoutMinutes?: number;
}

export interface EtlConfigurationProps {
  readonly lambdaTimeoutSeconds?: number;
  readonly lambdaMemorySizeMb?: number;
  readonly batchSize?: number;
  readonly batchWindowSeconds?: number;
  readonly visibilityTimeoutSeconds?: number;
  readonly messageRetentionDays?: number;
  readonly maxReceiveCount?: number;
}

export class ConfigurationBuilder {
  static buildKnowledgeBaseConfig(
    scope: Construct,
    props?: KnowledgeBaseConfigurationProps,
  ): ResolvedConfiguration {
    const stack = cdk.Stack.of(scope);

    return {
      embedding: ConfigurationBuilder.buildEmbeddingConfig(stack, props),
      vector: ConfigurationBuilder.buildVectorConfig(props),
      cleanup: ConfigurationBuilder.buildCleanupConfig(props),
      inclusionPrefixes: props?.inclusionPrefixes ?? ['docs/'],
      useFoundationParsing: props?.useFoundationParsing ?? false,
      parsingPromptText: props?.parsingPromptText,
    };
  }

  static buildEtlConfiguration(
    props?: EtlConfigurationProps,
  ): EtlConfigurationProps {
    return {
      lambdaTimeoutSeconds: props?.lambdaTimeoutSeconds ?? 300,
      lambdaMemorySizeMb: props?.lambdaMemorySizeMb ?? 1024,
      batchSize: props?.batchSize ?? 10,
      batchWindowSeconds: props?.batchWindowSeconds ?? 60,
      visibilityTimeoutSeconds: props?.visibilityTimeoutSeconds ?? 600,
      messageRetentionDays: props?.messageRetentionDays ?? 4,
      maxReceiveCount: props?.maxReceiveCount ?? 3,
    };
  }

  private static buildEmbeddingConfig(
    stack: cdk.Stack,
    props?: KnowledgeBaseConfigurationProps,
  ): EmbeddingConfig {
    const modelId = props?.embeddingModel ?? 'amazon.titan-embed-text-v2:0';
    const dimension = props?.vectorDimension ?? 1024;

    if (
      modelId.includes('titan-embed-text-v2') &&
      ![256, 512, 1024].includes(dimension)
    ) {
      throw new Error(
        `Titan Embed Text v2 model supports 256, 512, or 1024 dimensions, but got ${dimension}`,
      );
    }
    if (
      modelId.includes('titan-embed-text-v1') &&
      ![1536].includes(dimension)
    ) {
      throw new Error(
        `Titan Embed Text v1 model requires 1536 dimensions, but got ${dimension}. ` +
          `Please set vectorDimension to 1536 or use a different embedding model.`,
      );
    }

    return {
      modelArn: resolveEmbeddingModelArn(stack.region, undefined),
      modelId,
      dimension,
      dataType: props?.dataType ?? 'float32',
      embeddingDataType: props?.embeddingDataType ?? 'FLOAT32',
    };
  }

  private static buildVectorConfig(
    props?: KnowledgeBaseConfigurationProps,
  ): VectorConfig {
    return {
      distanceMetric: props?.distanceMetric ?? 'cosine',
      dimension: props?.vectorDimension ?? 1024,
      dataType: props?.dataType ?? 'float32',
    };
  }

  private static buildCleanupConfig(
    props?: KnowledgeBaseConfigurationProps,
  ): CleanupConfig {
    return {
      enabled: props?.cleanupEnabled ?? true,
      timeoutMinutes: props?.cleanupTimeoutMinutes ?? 15,
    };
  }

  static validate(config: ResolvedConfiguration): void {
    if (config.vector.dimension !== config.embedding.dimension) {
      throw new Error(
        `Vector dimension (${config.vector.dimension}) must match embedding model dimension (${config.embedding.dimension})`,
      );
    }

    if (config.inclusionPrefixes.length === 0) {
      throw new Error('At least one inclusion prefix must be specified');
    }

    // parsingPromptText is optional even when useFoundationParsing is true;
    // Bedrock falls back to default prompts if not specified.
  }

  static withEnvironmentOverrides(
    config: ResolvedConfiguration,
    environmentOverrides?: Partial<KnowledgeBaseConfigurationProps>,
  ): ResolvedConfiguration {
    if (!environmentOverrides) {
      return config;
    }

    return {
      ...config,
      embedding: {
        ...config.embedding,
        dimension:
          environmentOverrides.vectorDimension ?? config.embedding.dimension,
      },
      vector: {
        ...config.vector,
        distanceMetric:
          environmentOverrides.distanceMetric ?? config.vector.distanceMetric,
        dimension:
          environmentOverrides.vectorDimension ?? config.vector.dimension,
      },
      cleanup: {
        ...config.cleanup,
        enabled: environmentOverrides.cleanupEnabled ?? config.cleanup.enabled,
        timeoutMinutes:
          environmentOverrides.cleanupTimeoutMinutes ??
          config.cleanup.timeoutMinutes,
      },
      inclusionPrefixes:
        environmentOverrides.inclusionPrefixes ?? config.inclusionPrefixes,
      useFoundationParsing:
        environmentOverrides.useFoundationParsing ??
        config.useFoundationParsing,
      parsingPromptText:
        environmentOverrides.parsingPromptText ?? config.parsingPromptText,
    };
  }
}
