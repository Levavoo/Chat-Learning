import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';

const RUNBOOK_LINK = 'docs/runbooks/budget_pacing.md';

export interface BudgetPacingProps {
  /** Resource name prefix */
  readonly prefix: string;
  /** Environment name */
  readonly envName: string;
  /** Monthly budget in USD as reported by Cost Explorer (pre-discount, incl. tax) */
  readonly monthlyBudgetUsd: number;
  /** ARN of the maintenance-mode CloudFront KeyValueStore */
  readonly maintenanceKvsArn: string;
  /** ChatHandler function to throttle when over budget */
  readonly chatHandler: lambda.IFunction;
  /** SNS topic for pacing notifications */
  readonly alertTopic: sns.ITopic;
  /** SSM parameter holding the maintenance reason */
  readonly maintenanceReasonParameter: ssm.IStringParameter;
  /** CloudFront distribution ID for cache invalidation on maintenance disable */
  readonly distributionId: string;
  /** Log retention for the pacing Lambda @default ONE_MONTH */
  readonly logRetention?: logs.RetentionDays;
}

/**
 * Budget pacing: a scheduled Lambda that distributes the fixed monthly budget
 * across the remaining days and takes the service offline when cumulative
 * spend exceeds the prorated curve.
 *
 * Runs twice daily (06:00 and 12:00 UTC) — before and during the 6-21 Uhr SLA
 * window. Both invocations can enable and disable maintenance.
 *
 * Deliberately NOT VPC-attached: the Lambda only calls public AWS APIs
 * (Cost Explorer, SSM, CloudFront KVS, Lambda, SNS). Placing a cost-control
 * Lambda behind a NAT Gateway would add cost and cold-start latency for
 * nothing.
 *
 * The maintenance mechanism itself is reused from RFC 0005 (KVS flag +
 * ChatHandler reserved concurrency 0) — this construct only decides *when*
 * to flip it. See RFC 0006.
 */
export class BudgetPacing extends Construct {
  public readonly handler: lambda.Function;
  public readonly errorAlarm: cloudwatch.Alarm;

  constructor(scope: Construct, id: string, props: BudgetPacingProps) {
    super(scope, id);

    const {
      prefix,
      envName,
      monthlyBudgetUsd,
      maintenanceKvsArn,
      chatHandler,
      alertTopic,
      maintenanceReasonParameter,
      distributionId,
      logRetention = logs.RetentionDays.ONE_MONTH,
    } = props;

    const functionName = `${prefix}-budget-pacing-${envName}`;

    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/aws/lambda/${functionName}`,
      retention: logRetention,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.handler = new lambda.Function(this, 'Handler', {
      functionName,
      description:
        'Daily budget pacing — toggles maintenance mode when spend exceeds the prorated curve',
      runtime: lambda.Runtime.PYTHON_3_13,
      architecture: lambda.Architecture.X86_64,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(
        path.join(__dirname, '../../../../backend/src/budget_pacing/'),
      ),
      // CloudFront KVS requires SigV4a signing which needs the awscrt C library.
      // The standard Lambda Python runtime does not include it, so we ship it as
      // a pre-built layer (cdk/layers/awscrt-layer.zip, built for Linux x86_64).
      // The CI deploy image (node-aws) has neither Docker nor python3, so runtime
      // bundling is not possible — the zip is committed to the repo.
      layers: [
        new lambda.LayerVersion(this, 'AwsCrtLayer', {
          layerVersionName: `${prefix}-awscrt-${envName}`,
          description: 'awscrt library for SigV4a signing (CloudFront KVS)',
          compatibleRuntimes: [lambda.Runtime.PYTHON_3_13],
          compatibleArchitectures: [lambda.Architecture.X86_64],
          code: lambda.Code.fromAsset(
            path.join(__dirname, '../../../layers/awscrt-layer.zip'),
          ),
        }),
      ],
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      logGroup,
      environment: {
        ENV_NAME: envName,
        MONTHLY_BUDGET_USD: String(monthlyBudgetUsd),
        KVS_ARN: maintenanceKvsArn,
        CHAT_HANDLER_NAME: chatHandler.functionName,
        SNS_TOPIC_ARN: alertTopic.topicArn,
        MAINTENANCE_REASON_PARAM: maintenanceReasonParameter.parameterName,
        DISTRIBUTION_ID: distributionId,
      },
    });

    // Cost Explorer does not support resource-level permissions — the wildcard
    // is an AWS-imposed limitation, not a scoping oversight.
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ReadCostExplorer',
        effect: iam.Effect.ALLOW,
        actions: ['ce:GetCostAndUsage'],
        resources: ['*'],
      }),
    );

    // Same three KVS grants the maintenance-switch script needs. GetKey is
    // easy to forget.
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ToggleMaintenanceFlag',
        effect: iam.Effect.ALLOW,
        actions: [
          'cloudfront-keyvaluestore:DescribeKeyValueStore',
          'cloudfront-keyvaluestore:UpdateKeys',
          'cloudfront-keyvaluestore:GetKey',
        ],
        resources: [maintenanceKvsArn],
      }),
    );

    // Invalidate cached maintenance pages when disabling maintenance.
    // CACHING_OPTIMIZED has a 24h TTL; without this the stale page persists.
    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvalidateCloudFrontCache',
        effect: iam.Effect.ALLOW,
        actions: ['cloudfront:CreateInvalidation'],
        resources: [
          `arn:aws:cloudfront::${cdk.Stack.of(this).account}:distribution/${distributionId}`,
        ],
      }),
    );

    this.handler.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'ThrottleChatHandler',
        effect: iam.Effect.ALLOW,
        actions: [
          'lambda:PutFunctionConcurrency',
          'lambda:DeleteFunctionConcurrency',
        ],
        resources: [chatHandler.functionArn],
      }),
    );

    maintenanceReasonParameter.grantRead(this.handler);
    maintenanceReasonParameter.grantWrite(this.handler);
    alertTopic.grantPublish(this.handler);

    // Every 2 hours from 06:00 to 20:00 UTC (08:00–22:00 CET), covering the
    // full SLA window (6–21 Uhr CET) plus an early-morning pre-check.
    // More frequent checks reduce the Cost Explorer delay impact — a spike
    // detected at 10:00 doesn't have to wait until 12:00 for the next eval.
    new events.Rule(this, 'Schedule', {
      ruleName: `${prefix}-budget-pacing-${envName}`,
      description: 'Budget pacing evaluation every 2h during service hours',
      schedule: events.Schedule.cron({
        minute: '0',
        hour: '6,8,10,12,14,16,18,20',
      }),
      targets: [new targets.LambdaFunction(this.handler)],
    });

    this.errorAlarm = new cloudwatch.Alarm(this, 'ErrorAlarm', {
      alarmName: `${prefix}-budget-pacing-errors-${envName}`,
      alarmDescription: `Budget pacing Lambda failed — cost control may be inactive. Runbook: ${RUNBOOK_LINK}`,
      metric: this.handler.metricErrors({
        period: cdk.Duration.minutes(5),
        statistic: cloudwatch.Stats.SUM,
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    this.errorAlarm.addAlarmAction(new actions.SnsAction(alertTopic));

    new cdk.CfnOutput(this, 'FunctionName', {
      value: functionName,
      description: 'Budget pacing Lambda function name',
    });
  }
}
