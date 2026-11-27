import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import { Construct } from 'constructs';

import { deterministicName } from '../../constants/resource-names';
import { CleanupFinalizer, DeletionBehavior } from './cleanup-finalizer';
import { S3Factory } from '../../factories/s3-factory';
import { ResolvedConfiguration } from '../../interfaces/common';
import {
  resolveEmbeddingModelArn,
  resolveParsingModelArn,
} from '../../utils/embedding-models';
import {
  createS3BucketPolicy,
  createBedrockInvokePolicy,
  createS3VectorsDataPlanePolicy,
  createS3VectorsControlPlanePolicy,
  createCloudWatchLogsPolicy,
} from '../../utils/iam';

export interface S3ToS3VectorsKnowledgeBaseProps {
  readonly configuration?: ResolvedConfiguration;
  readonly inclusionPrefixes?: string[];
  readonly embeddingModelArn?: string;
  readonly vectorDimension?: number;
  readonly useFoundationParsing?: boolean;
  readonly parsingModelArn?: string;
  readonly parsingPromptText?: string;
  readonly distanceMetric?: 'cosine' | 'euclidean';
  readonly dataType?: 'float32';
  readonly embeddingDataType?: 'FLOAT32' | 'BINARY';
  readonly deletionBehavior?: DeletionBehavior;
  readonly dataDeletionPolicy?: 'DELETE' | 'RETAIN';
  readonly knowledgeBaseRole?: iam.IRole;
  readonly ingestionBucket?: s3.IBucket;
  /** Physical-name suffix for an additional isolated retrieval slot. */
  readonly resourceNameSuffix?: string;
  /** New physical names only. */
  readonly physicalNameEnvironment?: string;
  /** Only applied when this construct creates the bucket. */
  readonly ingestionBucketLifecycleRules?: s3.LifecycleRule[];
}

/** Bedrock Knowledge Base + S3 Vectors + DataSource + cleanup finalizer. */
export class S3ToS3VectorsKnowledgeBase extends Construct {
  public readonly knowledgeBaseId: string;
  public readonly knowledgeBaseArn: string;
  public readonly ingestionBucket: s3.IBucket;
  public readonly knowledgeBaseRole: iam.IRole;
  public readonly vectorBucketName: string;
  public readonly vectorIndexName: string;
  public readonly vectorBucketArn: string;
  public readonly vectorIndexArn: string;
  public readonly dataSourceId: string;

  constructor(
    scope: Construct,
    id: string,
    props?: S3ToS3VectorsKnowledgeBaseProps,
  ) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const envName = stack.node.tryGetContext('environment') || 'dev';

    let inclusionPrefixes: string[];
    let vectorDimension: number;
    let useFoundationParsing: boolean;
    let embeddingModelArn: string;
    let parsingModelArn: string;
    let embeddingDataType: 'FLOAT32' | 'BINARY';
    let distanceMetric: 'cosine' | 'euclidean';
    let dataType: 'float32';

    if (props?.configuration) {
      const config = props.configuration;
      inclusionPrefixes = config.inclusionPrefixes;
      vectorDimension = config.embedding.dimension;
      useFoundationParsing = config.useFoundationParsing;
      embeddingModelArn = config.embedding.modelArn;
      parsingModelArn = resolveParsingModelArn(
        stack.region,
        props?.parsingModelArn,
      );
      embeddingDataType = config.embedding.embeddingDataType as
        'FLOAT32' | 'BINARY';
      distanceMetric = config.vector.distanceMetric as 'cosine' | 'euclidean';
      dataType = config.vector.dataType as 'float32';
    } else {
      inclusionPrefixes = props?.inclusionPrefixes ?? ['docs/'];
      vectorDimension = props?.vectorDimension ?? 1024;
      useFoundationParsing = props?.useFoundationParsing ?? false;
      embeddingModelArn = resolveEmbeddingModelArn(
        stack.region,
        props?.embeddingModelArn,
      );
      parsingModelArn = resolveParsingModelArn(
        stack.region,
        props?.parsingModelArn,
      );
      embeddingDataType = props?.embeddingDataType ?? 'FLOAT32';
      distanceMetric = props?.distanceMetric ?? 'cosine';
      dataType = props?.dataType ?? 'float32';
    }

    const deletionBehavior = props?.deletionBehavior ?? 'DELETE';
    const dataDeletionPolicy = props?.dataDeletionPolicy ?? 'DELETE';
    const namedPurpose = (purpose: string) =>
      props?.resourceNameSuffix
        ? `${purpose}-${props.resourceNameSuffix}`
        : purpose;

    this.ingestionBucket =
      props?.ingestionBucket ??
      S3Factory.createBucket(stack, 'IngestionBucket', {
        purpose: 'kb-ingestion-bucket',
        environment: envName,
        physicalNameEnvironment: props?.physicalNameEnvironment,
        lifecycleRules: props?.ingestionBucketLifecycleRules,
      });

    this.knowledgeBaseRole =
      props?.knowledgeBaseRole ??
      this.createKnowledgeBaseRole(
        deterministicName(
          stack,
          iam.CfnRole.CFN_RESOURCE_TYPE_NAME,
          namedPurpose('kb-role'),
          props?.physicalNameEnvironment,
        ),
        this.ingestionBucket,
        inclusionPrefixes,
        embeddingModelArn,
        useFoundationParsing ? parsingModelArn : undefined,
      );

    const vectorBucketName = deterministicName(
      stack,
      s3.CfnBucket.CFN_RESOURCE_TYPE_NAME,
      namedPurpose('vector-bucket'),
      props?.physicalNameEnvironment,
    );
    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {
      vectorBucketName: vectorBucketName,
    });

    const vectorIndexName = deterministicName(
      stack,
      s3vectors.CfnIndex.CFN_RESOURCE_TYPE_NAME,
      namedPurpose('vector-index'),
      props?.physicalNameEnvironment,
    );
    const vectorIndex = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketArn: vectorBucket.attrVectorBucketArn,
      indexName: vectorIndexName,
      dataType: dataType ?? 'float32',
      dimension: vectorDimension,
      distanceMetric: distanceMetric ?? 'cosine',
      metadataConfiguration: {
        nonFilterableMetadataKeys: [
          'AMAZON_BEDROCK_TEXT',
          'AMAZON_BEDROCK_METADATA',
        ],
      },
    });

    const knowledgeBase = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: deterministicName(
        stack,
        bedrock.CfnKnowledgeBase.CFN_RESOURCE_TYPE_NAME,
        namedPurpose('knowledge-base'),
        props?.physicalNameEnvironment,
      ),
      roleArn: this.knowledgeBaseRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: embeddingModelArn,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: {
              dimensions: vectorDimension,
              embeddingDataType: embeddingDataType ?? 'FLOAT32',
            },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: {
          vectorBucketArn: vectorBucket.attrVectorBucketArn,
          indexArn: vectorIndex.attrIndexArn,
        },
      },
    });

    const dataSource = this.createDataSource(
      deterministicName(
        stack,
        bedrock.CfnDataSource.CFN_RESOURCE_TYPE_NAME,
        namedPurpose('data-source'),
        props?.physicalNameEnvironment,
      ),
      knowledgeBase,
      this.ingestionBucket,
      inclusionPrefixes,
      useFoundationParsing,
      parsingModelArn,
      props?.parsingPromptText,
      dataDeletionPolicy,
    );

    const finalizer = new CleanupFinalizer(this, 'Finalizer', {
      knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
      dataSourceNamePrefix: dataSource.name,
      deletionBehavior,
      resourceNameSuffix: props?.resourceNameSuffix,
      physicalNameEnvironment: props?.physicalNameEnvironment,
    });

    if (deletionBehavior === 'RETAIN') {
      vectorBucket.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
      vectorIndex.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);
    }

    vectorIndex.node.addDependency(vectorBucket);
    knowledgeBase.node.addDependency(vectorIndex);
    dataSource.node.addDependency(knowledgeBase);
    finalizer.node.addDependency(dataSource);
    finalizer.node.addDependency(knowledgeBase);
    // Cleanup order: finalizer must wait for the vector resources.
    finalizer.node.addDependency(vectorIndex);
    finalizer.node.addDependency(vectorBucket);

    this.knowledgeBaseId = knowledgeBase.attrKnowledgeBaseId;
    this.knowledgeBaseArn = knowledgeBase.attrKnowledgeBaseArn;
    this.vectorBucketName = vectorBucketName;
    this.vectorIndexName = vectorIndexName;
    this.vectorBucketArn = vectorBucket.attrVectorBucketArn;
    this.vectorIndexArn = vectorIndex.attrIndexArn;
    this.dataSourceId = dataSource.attrDataSourceId;
  }

  private createKnowledgeBaseRole(
    roleName: string,
    ingestionBucket: s3.IBucket,
    inclusionPrefixes: string[],
    embeddingModelArn: string,
    parsingModelArn?: string,
  ): iam.IRole {
    const stack = cdk.Stack.of(this);

    const s3Policies = createS3BucketPolicy(ingestionBucket, inclusionPrefixes);

    const modelArns = [embeddingModelArn];
    if (parsingModelArn) {
      modelArns.push(parsingModelArn);
    }

    // Inline policies for atomic creation.
    const role = new iam.Role(this, 'KnowledgeBaseRole', {
      roleName,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Role for Bedrock Knowledge Base with S3 Vectors storage',
      inlinePolicies: {
        S3BucketAccess: new iam.PolicyDocument({
          statements: s3Policies,
        }),
        BedrockModelAccess: new iam.PolicyDocument({
          statements: [createBedrockInvokePolicy(modelArns)],
        }),
        S3VectorsDataPlane: new iam.PolicyDocument({
          statements: [createS3VectorsDataPlanePolicy()],
        }),
        S3VectorsControlPlane: new iam.PolicyDocument({
          statements: [createS3VectorsControlPlanePolicy()],
        }),
        CloudWatchLogs: new iam.PolicyDocument({
          statements: [createCloudWatchLogsPolicy(stack.region, stack.account)],
        }),
      },
    });

    return role;
  }

  private createDataSource(
    dataSourceName: string,
    knowledgeBase: bedrock.CfnKnowledgeBase,
    ingestionBucket: s3.IBucket,
    inclusionPrefixes: string[],
    useFoundationParsing: boolean,
    parsingModelArn: string,
    parsingPromptText: string | undefined,
    dataDeletionPolicy: 'DELETE' | 'RETAIN',
  ): bedrock.CfnDataSource {
    const maybeParsing = useFoundationParsing
      ? {
          parsingConfiguration: {
            parsingStrategy: 'BEDROCK_FOUNDATION_MODEL',
            bedrockFoundationModelConfiguration: {
              modelArn: parsingModelArn,
              ...(parsingPromptText && {
                parsingPrompt: { parsingPromptText },
              }),
            },
          },
        }
      : {};

    // Documents are pre-chunked by the ETL pipeline; Bedrock ingests as-is.
    const buildChunkingConfig = () => ({
      chunkingStrategy: 'NONE' as const,
    });

    const dataSource = new bedrock.CfnDataSource(this, 'DataSource', {
      name: dataSourceName,
      description: `S3 data source for Knowledge Base - ${dataSourceName}`,
      knowledgeBaseId: knowledgeBase.attrKnowledgeBaseId,
      dataDeletionPolicy,
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: {
          bucketArn: ingestionBucket.bucketArn,
          inclusionPrefixes,
        },
      },
      vectorIngestionConfiguration: {
        chunkingConfiguration: buildChunkingConfig(),
        ...maybeParsing,
      },
    });

    dataSource.node.addDependency(knowledgeBase);
    return dataSource;
  }
}
