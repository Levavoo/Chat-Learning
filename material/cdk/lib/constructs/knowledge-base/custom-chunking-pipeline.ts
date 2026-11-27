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

import { EtlConfig } from '../../config/kb/etl-config';
import { deterministicName } from '../../constants/resource-names';

export interface CustomChunkingPipelineProps {
  readonly etlConfig: EtlConfig;
  readonly destinationBucket: s3.IBucket;
  /** renate-etl-lambda; built by the ETL image CI job. */
  readonly etlRepo: ecr.IRepository;
  /** Resolved from SSM /{env}/renate/etl-image-tag. */
  readonly etlImageTag: string;
}

export class CustomChunkingPipeline extends Construct {
  public readonly intermediateBucket: s3.Bucket;
  public readonly processingQueue: sqs.Queue;
  public readonly dlq: sqs.Queue;
  public readonly chunkingLambda: lambda.Function;

  constructor(
    scope: Construct,
    id: string,
    props: CustomChunkingPipelineProps,
  ) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const { etlConfig, destinationBucket, etlRepo, etlImageTag } = props;

    this.intermediateBucket = new s3.Bucket(this, 'IntermediateBucket', {
      bucketName: deterministicName(
        stack,
        s3.CfnBucket.CFN_RESOURCE_TYPE_NAME,
        'kb-intermediate',
      ),
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
    });

    this.dlq = new sqs.Queue(this, 'ChunkingDLQ', {
      queueName: deterministicName(
        stack,
        sqs.CfnQueue.CFN_RESOURCE_TYPE_NAME,
        'chunking-failed',
      ),
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    this.processingQueue = new sqs.Queue(this, 'ChunkingQueue', {
      queueName: deterministicName(
        stack,
        sqs.CfnQueue.CFN_RESOURCE_TYPE_NAME,
        'chunking-batching',
      ),
      visibilityTimeout: cdk.Duration.seconds(
        etlConfig.visibilityTimeoutSeconds,
      ),
      retentionPeriod: cdk.Duration.days(etlConfig.messageRetentionDays),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
      deadLetterQueue: {
        queue: this.dlq,
        maxReceiveCount: etlConfig.maxReceiveCount,
      },
    });

    this.intermediateBucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.SqsDestination(this.processingQueue),
    );

    const chunkingRole = new iam.Role(this, 'ChunkingLambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for Custom Chunking Lambda',
      inlinePolicies: {
        LambdaBasicExecution: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
              ],
              resources: [
                `arn:aws:logs:${stack.region}:${stack.account}:log-group:/aws/lambda/*`,
              ],
            }),
          ],
        }),
        S3Access: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              actions: ['s3:GetObject', 's3:ListBucket'],
              resources: [
                this.intermediateBucket.bucketArn,
                `${this.intermediateBucket.bucketArn}/*`,
              ],
            }),
            new iam.PolicyStatement({
              actions: ['s3:PutObject', 's3:PutObjectAcl', 's3:ListBucket'],
              resources: [
                destinationBucket.bucketArn,
                `${destinationBucket.bucketArn}/*`,
              ],
            }),
          ],
        }),
        BedrockAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['bedrock:InvokeModel'],
              resources: [`*`],
            }),
          ],
        }),
      },
    });

    this.chunkingLambda = new lambda.DockerImageFunction(
      this,
      'ChunkingLambda',
      {
        functionName: deterministicName(
          stack,
          lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
          'custom-chunking',
        ),
        code: lambda.DockerImageCode.fromEcr(etlRepo, {
          tagOrDigest: etlImageTag,
        }),
        role: chunkingRole,
        architecture: lambda.Architecture.X86_64,
        timeout: cdk.Duration.seconds(etlConfig.lambdaTimeoutSeconds),
        memorySize: etlConfig.lambdaMemorySizeMb,
        environment: {
          ETL_INGEST_BUCKET: this.intermediateBucket.bucketName,
          ETL_OUTPUT_BUCKET: destinationBucket.bucketName,
          LOG_LEVEL: 'INFO',
          CONTEXTUAL_GROUNDING_ENABLED: String(
            etlConfig.contextualGrounding?.enabled ?? true,
          ),
          CONTEXTUAL_GROUNDING_MODEL_ID:
            etlConfig.contextualGrounding?.modelId ?? 'eu.amazon.nova-pro-v1:0',
        },
        logGroup: new logs.LogGroup(this, 'ChunkingLambdaLogGroup', {
          logGroupName: `/aws/lambda/${deterministicName(
            stack,
            lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
            'custom-chunking',
          )}`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      },
    );

    this.chunkingLambda.addEventSource(
      new lambdaEventSources.SqsEventSource(this.processingQueue, {
        batchSize: etlConfig.batchSize,
        maxBatchingWindow: cdk.Duration.seconds(etlConfig.batchWindowSeconds),
        reportBatchItemFailures: true,
      }),
    );
  }
}
