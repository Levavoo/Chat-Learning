import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import { Construct } from 'constructs';

export interface Bm25IndexBuilderProps {
  /** Holds chunks and the output index. */
  readonly ingestionBucket: s3.IBucket;
  readonly chunkPrefix?: string;
  readonly indexKey?: string;
  readonly debounceWindowSeconds?: number;
  /** renate-etl-lambda; built by the ETL image CI job. */
  readonly etlRepo: ecr.IRepository;
  /** Resolved from SSM /{env}/renate/etl-image-tag. */
  readonly etlImageTag: string;
  /** Refuse mutable/event-driven writes; direct builds must carry a validated manifest. */
  readonly immutableOnly?: boolean;
  readonly expectedKnowledgeBaseId?: string;
  readonly expectedDataSourceId?: string;
}

export class Bm25IndexBuilder extends Construct {
  public readonly builderLambda: lambda.DockerImageFunction;
  public readonly rebuildQueue: sqs.Queue;
  public readonly rebuildDlq: sqs.Queue;

  constructor(scope: Construct, id: string, props: Bm25IndexBuilderProps) {
    super(scope, id);

    const chunkPrefix = props.chunkPrefix ?? 'docs/';
    const indexKey = props.indexKey ?? 'bm25_index/index.json';
    // 5 min is the SQS maxBatchingWindow cap.
    const debounceWindow = props.debounceWindowSeconds ?? 300;

    const dockerCode = lambda.DockerImageCode.fromEcr(props.etlRepo, {
      tagOrDigest: props.etlImageTag,
      cmd: ['etl.bm25_index_builder.handler'],
    });

    const environment: Record<string, string> = {
      BM25_BUCKET: props.ingestionBucket.bucketName,
      BM25_CHUNK_PREFIX: chunkPrefix,
      BM25_INDEX_KEY: indexKey,
    };
    if (props.immutableOnly) {
      environment.BM25_IMMUTABLE_ONLY = 'true';
    }
    if (props.expectedKnowledgeBaseId) {
      environment.RETRIEVAL_KNOWLEDGE_BASE_ID = props.expectedKnowledgeBaseId;
    }
    if (props.expectedDataSourceId) {
      environment.RETRIEVAL_DATA_SOURCE_ID = props.expectedDataSourceId;
    }

    this.builderLambda = new lambda.DockerImageFunction(this, 'BuilderLambda', {
      code: dockerCode,
      architecture: lambda.Architecture.X86_64,
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      // Headroom (2 event-source + 1 direct) so bm25-rebuild.sh never hits
      // ReservedFunctionConcurrentInvocationLimitExceeded during a flood.
      reservedConcurrentExecutions: 5,
      description: 'Builds BM25 index from chunks in S3',
      environment,
      logGroup: new logs.LogGroup(this, 'BuilderLogGroup', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    props.ingestionBucket.grantRead(this.builderLambda);
    this.builderLambda.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['s3:PutObject'],
        resources: [`${props.ingestionBucket.bucketArn}/${indexKey}`],
      }),
    );
    this.builderLambda.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        // Immutable release indexes set their lifecycle tag in the same
        // PutObject; S3 evaluates it against PutObjectTagging separately.
        actions: ['s3:PutObject', 's3:PutObjectTagging'],
        resources: [`${props.ingestionBucket.bucketArn}/bm25_index/releases/*`],
      }),
    );

    // S3 ObjectCreated/Removed on docs/*.md → debounced SQS → full-corpus
    // rebuild. Rebuild is idempotent and ignores which file changed.
    const rebuildDlq = new sqs.Queue(this, 'RebuildDlq', {
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });
    this.rebuildDlq = rebuildDlq;

    const rebuildQueue = new sqs.Queue(this, 'RebuildQueue', {
      // debounceWindow + Lambda timeout (5 min) + 1 min buffer.
      visibilityTimeout: cdk.Duration.seconds(debounceWindow + 5 * 60 + 60),
      retentionPeriod: cdk.Duration.days(1),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      deadLetterQueue: {
        queue: rebuildDlq,
        maxReceiveCount: 3,
      },
    });
    this.rebuildQueue = rebuildQueue;

    props.ingestionBucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.SqsDestination(rebuildQueue),
      { prefix: chunkPrefix, suffix: '.md' },
    );
    props.ingestionBucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new s3n.SqsDestination(rebuildQueue),
      { prefix: chunkPrefix, suffix: '.md' },
    );

    this.builderLambda.addEventSource(
      new lambdaEventSources.SqsEventSource(rebuildQueue, {
        // Large batchSize collapses a full-corpus reprocess burst (one event
        // per doc) into a few rebuilds; small batchSize made it O(N²) and took
        // hours to drain (#590). Bounded by the 6MB batch-payload cap.
        // batchSize > 10 requires maxBatchingWindow.
        batchSize: 10000,
        maxBatchingWindow: cdk.Duration.seconds(debounceWindow),
        maxConcurrency: 2,
      }),
    );
  }
}
