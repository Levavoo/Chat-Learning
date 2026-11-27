import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as path from 'path';
import {
  AwsCustomResource,
  AwsCustomResourcePolicy,
  PhysicalResourceId,
} from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import { deterministicName } from '../../constants/resource-names';

import { createBedrockCleanupPolicy } from '../../utils/iam';

export type DeletionBehavior = 'DELETE' | 'RETAIN';

export interface CleanupFinalizerProps {
  readonly knowledgeBaseId?: string;
  readonly dataSourceNamePrefix?: string;
  /** Scoped IAM resources. */
  readonly knowledgeBaseArns?: string[];
  /** @default 'DELETE' */
  readonly deletionBehavior?: DeletionBehavior;
  readonly pollSeconds?: number;
  readonly timeoutMinutes?: number;
  /** Physical-name suffix for an additional isolated retrieval slot. */
  readonly resourceNameSuffix?: string;
  /** New physical names only. */
  readonly physicalNameEnvironment?: string;
  /** @deprecated use timeoutMinutes */
  readonly maxMinutes?: number;
}

/** Lambda-based finalizer that properly cleans up a Bedrock KB on stack delete. */
export class CleanupFinalizer extends Construct {
  public readonly cleanupFunction: NodejsFunction;

  constructor(scope: Construct, id: string, props: CleanupFinalizerProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);
    const deletionBehavior = props.deletionBehavior ?? 'DELETE';
    const namedPurpose = (purpose: string) =>
      props.resourceNameSuffix
        ? `${purpose}-${props.resourceNameSuffix}`
        : purpose;

    const cleanupRole = new iam.Role(this, 'CleanupRole', {
      roleName: deterministicName(
        stack,
        iam.CfnRole.CFN_RESOURCE_TYPE_NAME,
        namedPurpose('bedrock-cleanup-role'),
        props.physicalNameEnvironment,
      ),
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for Bedrock cleanup Lambda',
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
        BedrockCleanupPolicy: new iam.PolicyDocument({
          statements: [createBedrockCleanupPolicy()],
        }),
      },
    });

    this.cleanupFunction = new NodejsFunction(this, 'CleanupFunction', {
      functionName: deterministicName(
        stack,
        lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
        namedPurpose('bedrock-cleanup'),
        props.physicalNameEnvironment,
      ),
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(
        __dirname,
        '../../custom-resources/s3-cleanup/cleanup-handler.ts',
      ),
      handler: 'handler',
      role: cleanupRole,
      timeout: cdk.Duration.minutes(props.timeoutMinutes ?? 15),
      memorySize: 256,
      description:
        'Cleanup finalizer for Bedrock Knowledge Base and DataSource',
      bundling: {},
      logGroup: new logs.LogGroup(this, 'CleanupFunctionLogGroup', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    if (deletionBehavior === 'DELETE') {
      new AwsCustomResource(this, 'FinalizerResource', {
        onCreate: {
          service: 'lambda',
          action: 'invoke',
          parameters: {
            FunctionName: this.cleanupFunction.functionName,
            InvocationType: 'Event',
            Payload: JSON.stringify({ noop: true }),
          },
          physicalResourceId: PhysicalResourceId.of(
            `finalizer-${cdk.Names.uniqueId(this).slice(-12)}`,
          ),
        },
        onDelete: {
          service: 'lambda',
          action: 'invoke',
          parameters: {
            FunctionName: this.cleanupFunction.functionName,
            InvocationType: 'RequestResponse',
            Payload: stack.toJsonString({
              region: stack.region,
              knowledgeBaseId: props.knowledgeBaseId,
              dataSourceNamePrefix: props.dataSourceNamePrefix,
              pollSeconds: props.pollSeconds ?? 5,
              maxMinutes: props.timeoutMinutes ?? 15,
            }),
          },
        },
        policy: AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            sid: 'InvokeCleanupLambda',
            effect: iam.Effect.ALLOW,
            actions: ['lambda:InvokeFunction'],
            resources: [this.cleanupFunction.functionArn],
          }),
        ]),
        timeout: cdk.Duration.minutes(
          Math.min((props.timeoutMinutes ?? 15) + 1, 15),
        ),
      });
    } else {
      new cdk.CfnOutput(this, 'RetainedResourcesWarning', {
        value: `Deletion behavior set to RETAIN. Knowledge Base ${props.knowledgeBaseId} and associated resources will not be automatically cleaned up.`,
        description: 'Warning about retained resources',
      });
    }
  }
}
