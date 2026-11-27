import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

import { deterministicName } from '../../constants/resource-names';

export interface EtlAlarmsProps {
  /** Omit on a slot that shares another's transform pipeline (prevents duplicate alarm). */
  readonly transformLambda?: lambda.IFunction;
  /** Omit together with transformLambda. */
  readonly dlq?: sqs.IQueue;
  readonly kbSyncLambda?: lambda.IFunction;
  readonly alarmTopicArn?: string;
  readonly lambdaErrorThreshold?: number;
  readonly lambdaErrorEvaluationPeriods?: number;
  readonly lambdaTimeout?: cdk.Duration;
  readonly alertTopic?: sns.ITopic;
  readonly bm25BuilderLambda?: lambda.IFunction;
  readonly bm25RebuildDlq?: sqs.IQueue;
  readonly bm25BuilderTimeout?: cdk.Duration;
  /**
   * 'blue' | 'green' discriminator. deterministicName hashes on purpose alone,
   * so two EtlAlarms in the same stack must pass distinct slots or alarm names
   * collide (#494).
   */
  readonly slot?: string;
  /** New physical names only. */
  readonly physicalNameEnvironment?: string;
}

export class EtlAlarms extends Construct {
  public readonly dlqAlarm?: cloudwatch.Alarm;
  public readonly lambdaErrorAlarm?: cloudwatch.Alarm;
  public readonly lambdaDurationAlarm?: cloudwatch.Alarm;
  public readonly kbSyncErrorAlarm?: cloudwatch.Alarm;
  public readonly bm25BuilderErrorAlarm?: cloudwatch.Alarm;
  public readonly bm25BuilderDurationAlarm?: cloudwatch.Alarm;
  public readonly bm25RebuildDlqAlarm?: cloudwatch.Alarm;

  constructor(scope: Construct, id: string, props: EtlAlarmsProps) {
    super(scope, id);

    const {
      transformLambda,
      dlq,
      kbSyncLambda,
      lambdaErrorThreshold = 5,
      lambdaErrorEvaluationPeriods = 1,
      lambdaTimeout = cdk.Duration.seconds(300),
      alertTopic,
      bm25BuilderLambda,
      bm25RebuildDlq,
      bm25BuilderTimeout = cdk.Duration.minutes(5),
      slot,
      physicalNameEnvironment,
    } = props;

    const purpose = (base: string) => (slot ? `${base}-${slot}` : base);

    if (dlq) {
      this.dlqAlarm = new cloudwatch.Alarm(this, 'DlqDepthAlarm', {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          purpose('dlq-messages'),
          physicalNameEnvironment,
        ),
        alarmDescription:
          'Triggers when messages appear in the Dead Letter Queue',
        metric: dlq.metricApproximateNumberOfMessagesVisible({
          period: cdk.Duration.minutes(5),
          statistic: cloudwatch.Stats.MAXIMUM,
        }),
        threshold: 0,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    }

    if (transformLambda) {
      this.lambdaErrorAlarm = new cloudwatch.Alarm(this, 'LambdaErrorAlarm', {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          purpose('lambda-errors'),
          physicalNameEnvironment,
        ),
        alarmDescription: `Triggers when Lambda has ${lambdaErrorThreshold}+ errors in 5 minutes`,
        metric: transformLambda.metricErrors({
          period: cdk.Duration.minutes(5),
          statistic: cloudwatch.Stats.SUM,
        }),
        threshold: lambdaErrorThreshold,
        evaluationPeriods: lambdaErrorEvaluationPeriods,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });

      const timeoutMs = lambdaTimeout.toMilliseconds();
      const warningThreshold = timeoutMs * 0.8;

      this.lambdaDurationAlarm = new cloudwatch.Alarm(
        this,
        'LambdaDurationAlarm',
        {
          alarmName: deterministicName(
            cdk.Stack.of(this),
            cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            purpose('lambda-duration'),
            physicalNameEnvironment,
          ),
          alarmDescription: `Triggers when Lambda duration approaches timeout (>${warningThreshold}ms)`,
          metric: transformLambda.metricDuration({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.MAXIMUM,
          }),
          threshold: warningThreshold,
          evaluationPeriods: 2,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    if (kbSyncLambda) {
      this.kbSyncErrorAlarm = new cloudwatch.Alarm(this, 'KbSyncErrorAlarm', {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          purpose('kb-sync-errors'),
          physicalNameEnvironment,
        ),
        alarmDescription:
          'Triggers when KB sync trigger Lambda fails to start ingestion',
        metric: kbSyncLambda.metricErrors({
          period: cdk.Duration.minutes(5),
          statistic: cloudwatch.Stats.SUM,
        }),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    }

    if (bm25BuilderLambda) {
      this.bm25BuilderErrorAlarm = new cloudwatch.Alarm(
        this,
        'Bm25BuilderErrorAlarm',
        {
          alarmName: deterministicName(
            cdk.Stack.of(this),
            cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            purpose('bm25-builder-errors'),
            physicalNameEnvironment,
          ),
          alarmDescription:
            'Triggers when the BM25 index builder Lambda has 1+ errors in 5 minutes. ' +
            'See docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md',
          metric: bm25BuilderLambda.metricErrors({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.SUM,
          }),
          threshold: 1,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );

      const bm25TimeoutMs = bm25BuilderTimeout.toMilliseconds();
      const bm25WarningThreshold = bm25TimeoutMs * 0.8;

      this.bm25BuilderDurationAlarm = new cloudwatch.Alarm(
        this,
        'Bm25BuilderDurationAlarm',
        {
          alarmName: deterministicName(
            cdk.Stack.of(this),
            cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            purpose('bm25-builder-duration'),
            physicalNameEnvironment,
          ),
          alarmDescription:
            `Triggers when the BM25 index builder Lambda duration approaches timeout (>${bm25WarningThreshold}ms). ` +
            'A single full-corpus reprocess burst (#590) can legitimately produce several ' +
            'consecutive long invocations; evaluationPeriods=2 tolerates a brief burst while ' +
            'still catching a sustained problem. ' +
            'See docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md',
          metric: bm25BuilderLambda.metricDuration({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.MAXIMUM,
          }),
          threshold: bm25WarningThreshold,
          evaluationPeriods: 2,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    if (bm25RebuildDlq) {
      this.bm25RebuildDlqAlarm = new cloudwatch.Alarm(
        this,
        'Bm25RebuildDlqAlarm',
        {
          alarmName: deterministicName(
            cdk.Stack.of(this),
            cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
            purpose('bm25-rebuild-dlq-messages'),
            physicalNameEnvironment,
          ),
          alarmDescription:
            'Triggers when messages appear in the BM25 rebuild Dead Letter Queue ' +
            '(rebuild retries exhausted — the queue itself is debounced/idempotent and ' +
            'excluded from readiness-gate blocking, but a DLQ message always means a real ' +
            'failure). See docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md',
          metric: bm25RebuildDlq.metricApproximateNumberOfMessagesVisible({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.MAXIMUM,
          }),
          threshold: 0,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    if (this.dlqAlarm) {
      new cdk.CfnOutput(this, 'DlqAlarmArn', {
        value: this.dlqAlarm.alarmArn,
        description: 'Dead Letter Queue alarm ARN',
      });
    }

    if (this.lambdaErrorAlarm) {
      new cdk.CfnOutput(this, 'LambdaErrorAlarmArn', {
        value: this.lambdaErrorAlarm.alarmArn,
        description: 'Lambda error alarm ARN',
      });
    }

    if (this.lambdaDurationAlarm) {
      new cdk.CfnOutput(this, 'LambdaDurationAlarmArn', {
        value: this.lambdaDurationAlarm.alarmArn,
        description: 'Lambda duration alarm ARN',
      });
    }

    if (this.kbSyncErrorAlarm) {
      new cdk.CfnOutput(this, 'KbSyncErrorAlarmArn', {
        value: this.kbSyncErrorAlarm.alarmArn,
        description: 'KB sync trigger error alarm ARN',
      });
    }

    if (this.bm25BuilderErrorAlarm) {
      new cdk.CfnOutput(this, 'Bm25BuilderErrorAlarmArn', {
        value: this.bm25BuilderErrorAlarm.alarmArn,
        description: 'BM25 index builder Lambda error alarm ARN',
      });
    }

    if (this.bm25BuilderDurationAlarm) {
      new cdk.CfnOutput(this, 'Bm25BuilderDurationAlarmArn', {
        value: this.bm25BuilderDurationAlarm.alarmArn,
        description: 'BM25 index builder Lambda duration alarm ARN',
      });
    }

    if (this.bm25RebuildDlqAlarm) {
      new cdk.CfnOutput(this, 'Bm25RebuildDlqAlarmArn', {
        value: this.bm25RebuildDlqAlarm.alarmArn,
        description: 'BM25 rebuild DLQ alarm ARN',
      });
    }

    if (alertTopic) {
      const snsAction = new actions.SnsAction(alertTopic);
      this.dlqAlarm?.addAlarmAction(snsAction);
      this.lambdaErrorAlarm?.addAlarmAction(snsAction);
      this.lambdaDurationAlarm?.addAlarmAction(snsAction);
      this.kbSyncErrorAlarm?.addAlarmAction(snsAction);
      this.bm25BuilderErrorAlarm?.addAlarmAction(snsAction);
      this.bm25BuilderDurationAlarm?.addAlarmAction(snsAction);
      this.bm25RebuildDlqAlarm?.addAlarmAction(snsAction);
    }
  }
}
