import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';
import { deterministicName } from '../../constants/resource-names';

/**
 * Namespace/metric names MUST match the literal strings
 * `.gitlab/ci/scripts/retrieval-health-check.sh` passes to
 * `aws cloudwatch put-metric-data` exactly (namespace, metric name, and no
 * dimensions) — any drift here binds an alarm to a metric that's never
 * populated, and it sits silently in INSUFFICIENT_DATA/OK forever.
 */
const RUNBOOK_LINK =
  'docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md';

export interface RetrievalHealthAlarmsProps {
  /** Optional SNS topic for alarm notifications */
  readonly alertTopic?: sns.ITopic;
  /** Metric namespace published by the environment's scheduled health check. */
  readonly metricNamespace?: string;
}

/**
 * CloudWatch alarms watching the custom metrics published by the #494
 * scheduled `retrieval-health-check.sh` job. The namespace is supplied by the
 * environment config. Instantiate this construct only where that schedule is
 * enabled: `CheckExecutedAlarm` treats missing data as breaching.
 */
export class RetrievalHealthAlarms extends Construct {
  public readonly ingestionFailureAlarm: cloudwatch.Alarm;
  public readonly coherenceFailureAlarm: cloudwatch.Alarm;
  public readonly retentionPinMissingAlarm: cloudwatch.Alarm;
  public readonly checkExecutedAlarm: cloudwatch.Alarm;

  constructor(scope: Construct, id: string, props: RetrievalHealthAlarmsProps) {
    super(scope, id);

    const { alertTopic, metricNamespace = 'Renate/QA/Retrieval' } = props;

    const outcomeMetric = (metricName: string) =>
      new cloudwatch.Metric({
        namespace: metricNamespace,
        metricName,
        period: cdk.Duration.minutes(15),
        statistic: cloudwatch.Stats.MAXIMUM,
      });

    // Outcome alarms treat missing data as NOT_BREACHING so a scheduled-check
    // outage trips CheckExecutedAlarm instead of being conflated with
    // "check ran and failed".
    this.ingestionFailureAlarm = new cloudwatch.Alarm(
      this,
      'IngestionFailureAlarm',
      {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          'retrieval-ingestion-failure',
        ),
        alarmDescription:
          'Two consecutive scheduled health-check runs (~30 min apart) found a ' +
          'FAILED Bedrock ingestion job or a non-empty transform/BM25/chunking DLQ. ' +
          `See ${RUNBOOK_LINK}`,
        metric: outcomeMetric('IngestionFailure'),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    this.coherenceFailureAlarm = new cloudwatch.Alarm(
      this,
      'CoherenceFailureAlarm',
      {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          'retrieval-coherence-failure',
        ),
        alarmDescription:
          'Two consecutive scheduled health-check runs (~30 min apart) found the ' +
          'hybrid retrieval diagnostic reporting ok:false (semantic/BM25 release_id ' +
          `mismatch or manifest/artifact resolution failure). See ${RUNBOOK_LINK}`,
        metric: outcomeMetric('CoherenceFailure'),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    this.retentionPinMissingAlarm = new cloudwatch.Alarm(
      this,
      'RetentionPinMissingAlarm',
      {
        alarmName: deterministicName(
          cdk.Stack.of(this),
          cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
          'retrieval-retention-pin-missing',
        ),
        alarmDescription:
          'Two consecutive scheduled health-check runs (~30 min apart) found a ' +
          'retention-pin drift on the active/previous processed release artifacts ' +
          `(release-retention.mjs audit --fail-on-drift). See ${RUNBOOK_LINK}`,
        metric: outcomeMetric('RetentionPinMissing'),
        threshold: 1,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    // Heartbeat alarm uses treatMissingData: BREACHING so 3 consecutive
    // missed ~15-min cycles trip it on silence. It will read BREACHING from
    // stack deploy until the GitLab scheduled pipeline is enabled and has
    // completed one run — the CDK alarm and its data source ship through two
    // independent mechanisms. See the runbook's "enabling the schedule"
    // section.
    this.checkExecutedAlarm = new cloudwatch.Alarm(this, 'CheckExecutedAlarm', {
      alarmName: deterministicName(
        cdk.Stack.of(this),
        cloudwatch.CfnAlarm.CFN_RESOURCE_TYPE_NAME,
        'retrieval-check-executed-heartbeat',
      ),
      alarmDescription:
        'The #494 scheduled retrieval-health-check itself has not reported a ' +
        'CheckExecuted heartbeat for ~45 minutes (3 missed ~15-min cycles) — the ' +
        'pipeline schedule may be disabled, the runner may be down, or the script ' +
        `crashed before completing. See ${RUNBOOK_LINK}`,
      metric: new cloudwatch.Metric({
        namespace: metricNamespace,
        metricName: 'CheckExecuted',
        period: cdk.Duration.minutes(15),
        statistic: cloudwatch.Stats.SUM,
      }),
      threshold: 1,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.BREACHING,
    });

    if (alertTopic) {
      const snsAction = new actions.SnsAction(alertTopic);
      this.ingestionFailureAlarm.addAlarmAction(snsAction);
      this.coherenceFailureAlarm.addAlarmAction(snsAction);
      this.retentionPinMissingAlarm.addAlarmAction(snsAction);
      this.checkExecutedAlarm.addAlarmAction(snsAction);
    }
  }
}
