import * as iam from 'aws-cdk-lib/aws-iam';

export interface CustomResourceOperation {
  readonly service: string;
  readonly action: string;
  readonly parameters: Record<string, any>;
  readonly outputPaths?: string[];
  readonly ignoreErrorCodeMatches?: string[];
}

export interface CustomResourceConfig {
  readonly service: string;
  readonly createAction: string;
  readonly deleteAction: string;
  readonly updateAction?: string;
  readonly getAction?: string;
  readonly timeoutMinutes?: number;
  readonly ignoreErrorCodes?: string[];
  readonly policyStatements: iam.PolicyStatement[];
}

export interface EmbeddingConfig {
  readonly modelArn: string;
  readonly modelId: string;
  readonly dimension: number;
  readonly dataType: string;
  readonly embeddingDataType: string;
}

export interface VectorConfig {
  readonly distanceMetric: string;
  readonly dimension: number;
  readonly dataType: string;
}

export interface CleanupConfig {
  readonly enabled: boolean;
  readonly timeoutMinutes: number;
}

export interface ResolvedConfiguration {
  readonly embedding: EmbeddingConfig;
  readonly vector: VectorConfig;
  readonly cleanup: CleanupConfig;
  readonly inclusionPrefixes: string[];
  readonly useFoundationParsing: boolean;
  readonly parsingPromptText: string | undefined;
}

export enum DeletionBehavior {
  DELETE = 'DELETE',
  RETAIN = 'RETAIN',
  SNAPSHOT = 'SNAPSHOT',
}

export interface ResourceCreationResult {
  readonly resource: any;
  readonly outputs: Record<string, string>;
}
