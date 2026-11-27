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

/** Properties for the TransformPipeline construct */
export interface TransformPipelineProps {
  /** ETL configuration */
  readonly etlConfig: EtlConfig;
  /** Source bucket for raw data */
  readonly sourceBucket: s3.IBucket;
  /** Destination bucket for processed data */
  readonly destinationBucket: s3.IBucket;
  /** S3 prefix filter for event notifications */
  readonly sourcePrefix?: string;
  /** S3 suffix filter for event notifications */
  readonly sourceSuffix?: string;
  /** ETL runtime ECR repository (renate-etl-lambda), built by build-etl-image:dev */
  readonly etlRepo: ecr.IRepository;
  /** ETL image tag/digest, resolved from SSM /{env}/renate/etl-image-tag */
  readonly etlImageTag: string;
}

/** Transform pipeline with SQS batching and Lambda processing triggered by S3 events */
export class TransformPipeline extends Construct {
  public readonly dlq: sqs.Queue;
  public readonly processingQueue: sqs.Queue;
  public readonly transformLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: TransformPipelineProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const {
      etlConfig,
      sourceBucket,
      destinationBucket,
      sourcePrefix,
      sourceSuffix,
      etlRepo,
      etlImageTag,
    } = props;

    this.dlq = new sqs.Queue(this, 'DLQ', {
      queueName: deterministicName(
        stack,
        sqs.CfnQueue.CFN_RESOURCE_TYPE_NAME,
        'failed-messages',
      ),
      retentionPeriod: cdk.Duration.days(14),
      encryption: sqs.QueueEncryption.SQS_MANAGED,
    });

    this.processingQueue = new sqs.Queue(this, 'ProcessingQueue', {
      queueName: deterministicName(
        stack,
        sqs.CfnQueue.CFN_RESOURCE_TYPE_NAME,
        'event-batching',
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

    const hasFilter = sourcePrefix || sourceSuffix;

    if (hasFilter) {
      const notificationFilter: s3.NotificationKeyFilter = {
        ...(sourcePrefix && { prefix: sourcePrefix }),
        ...(sourceSuffix && { suffix: sourceSuffix }),
      };

      sourceBucket.addEventNotification(
        s3.EventType.OBJECT_CREATED,
        new s3n.SqsDestination(this.processingQueue),
        notificationFilter,
      );
      sourceBucket.addEventNotification(
        s3.EventType.OBJECT_REMOVED,
        new s3n.SqsDestination(this.processingQueue),
        notificationFilter,
      );
    } else {
      sourceBucket.addEventNotification(
        s3.EventType.OBJECT_CREATED,
        new s3n.SqsDestination(this.processingQueue),
      );
      sourceBucket.addEventNotification(
        s3.EventType.OBJECT_REMOVED,
        new s3n.SqsDestination(this.processingQueue),
      );
    }

    const transformRole = new iam.Role(this, 'TransformLambdaRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for ETL transform Lambda',
      roleName: deterministicName(
        stack,
        iam.CfnRole.CFN_RESOURCE_TYPE_NAME,
        'etl-transform-lambda-role',
      ),
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
        XRayTracing: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords'],
              resources: ['*'],
            }),
          ],
        }),
        S3Access: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['s3:ListBucket', 's3:HeadBucket'],
              resources: [sourceBucket.bucketArn, destinationBucket.bucketArn],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['s3:GetObject', 's3:GetObjectVersion'],
              resources: [`${sourceBucket.bucketArn}/*`],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['s3:PutObject', 's3:PutObjectAcl'],
              resources: [`${destinationBucket.bucketArn}/*`],
            }),
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: ['s3:DeleteObject'],
              resources: [`${destinationBucket.bucketArn}/*`],
            }),
          ],
        }),
        SQSAccess: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'sqs:ReceiveMessage',
                'sqs:DeleteMessage',
                'sqs:GetQueueAttributes',
                'sqs:ChangeMessageVisibility',
              ],
              resources: [this.processingQueue.queueArn],
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

    this.transformLambda = new lambda.DockerImageFunction(
      this,
      'TransformLambda',
      {
        functionName: deterministicName(
          stack,
          lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
          'etl-transform',
        ),
        code: lambda.DockerImageCode.fromEcr(etlRepo, {
          tagOrDigest: etlImageTag,
        }),
        role: transformRole,
        architecture: lambda.Architecture.X86_64,
        timeout: cdk.Duration.seconds(etlConfig.lambdaTimeoutSeconds),
        memorySize: etlConfig.lambdaMemorySizeMb,
        environment: {
          ETL_INGEST_BUCKET: sourceBucket.bucketName,
          ETL_OUTPUT_BUCKET: destinationBucket.bucketName,
          LOG_LEVEL: 'INFO',
          CONTEXTUAL_GROUNDING_ENABLED: String(
            etlConfig.contextualGrounding?.enabled ?? true,
          ),
          CONTEXTUAL_GROUNDING_MODEL_ID:
            etlConfig.contextualGrounding?.modelId ?? 'us.amazon.nova-pro-v1:0',
          ENRICHMENT_ENABLED: String(etlConfig.enrichment?.enabled ?? false),
          ENRICHMENT_MODEL_ID:
            etlConfig.enrichment?.modelId ?? 'eu.amazon.nova-lite-v1:0',
        },
        tracing: lambda.Tracing.ACTIVE,
        logGroup: new logs.LogGroup(this, 'TransformLambdaLogGroup', {
          logGroupName: `/aws/lambda/${deterministicName(
            stack,
            lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
            'etl-transform',
          )}`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      },
    );

    this.transformLambda.addEventSource(
      new lambdaEventSources.SqsEventSource(this.processingQueue, {
        batchSize: etlConfig.batchSize,
        maxBatchingWindow: cdk.Duration.seconds(etlConfig.batchWindowSeconds),
        reportBatchItemFailures: true,
      }),
    );
  }
}
