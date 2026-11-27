import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambdaNodejs from 'aws-cdk-lib/aws-lambda-nodejs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import { Construct } from 'constructs';
import * as path from 'path';

import { deterministicName } from '../../constants/resource-names';

export interface KbSyncTriggerProps {
  readonly ingestionBucket: s3.IBucket;
  readonly knowledgeBaseId: string;
  readonly dataSourceId: string;
  readonly prefix?: string;
  /** One notification per suffix. */
  readonly suffixes?: string[];
  /** Physical-name suffix for an additional isolated retrieval slot. */
  readonly resourceNameSuffix?: string;
  /** New physical names only. */
  readonly physicalNameEnvironment?: string;
}

/** Starts a Bedrock KB ingestion job on S3 ObjectCreated/Removed events. */
export class KbSyncTrigger extends Construct {
  public readonly syncLambda: lambda.IFunction;

  constructor(scope: Construct, id: string, props: KbSyncTriggerProps) {
    super(scope, id);

    const {
      ingestionBucket,
      knowledgeBaseId,
      dataSourceId,
      prefix,
      suffixes,
      resourceNameSuffix,
      physicalNameEnvironment,
    } = props;

    this.syncLambda = new lambdaNodejs.NodejsFunction(this, 'SyncLambda', {
      functionName: deterministicName(
        cdk.Stack.of(this),
        lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
        resourceNameSuffix
          ? `kb-sync-trigger-${resourceNameSuffix}`
          : 'kb-sync-trigger',
        physicalNameEnvironment,
      ),
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'handler',
      entry: path.join(
        __dirname,
        '../../custom-resources/kb-sync-trigger/kb-sync-handler.ts',
      ),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        KNOWLEDGE_BASE_ID: knowledgeBaseId,
        DATA_SOURCE_ID: dataSourceId,
      },
      description: 'Triggers Bedrock KB sync when new documents are uploaded',
      tracing: lambda.Tracing.ACTIVE,
      logGroup: new logs.LogGroup(this, 'SyncLambdaLogGroup', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    this.syncLambda.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:StartIngestionJob'],
        resources: [
          `arn:aws:bedrock:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:knowledge-base/${knowledgeBaseId}`,
        ],
      }),
    );

    // Needed for S3 event metadata.
    ingestionBucket.grantRead(this.syncLambda);

    const filterSuffixes = suffixes ?? [undefined];
    for (const suffix of filterSuffixes) {
      ingestionBucket.addEventNotification(
        s3.EventType.OBJECT_CREATED,
        new s3n.LambdaDestination(this.syncLambda),
        {
          ...(prefix && { prefix }),
          ...(suffix && { suffix }),
        },
      );
      ingestionBucket.addEventNotification(
        s3.EventType.OBJECT_REMOVED,
        new s3n.LambdaDestination(this.syncLambda),
        {
          ...(prefix && { prefix }),
          ...(suffix && { suffix }),
        },
      );
    }

    new cdk.CfnOutput(this, 'SyncLambdaArn', {
      value: this.syncLambda.functionArn,
      description: 'KB Sync Trigger Lambda ARN',
    });
  }
}
