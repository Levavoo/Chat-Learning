import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';
import { BedrockTokenAlarmConfig } from '../../config/chatbot-config';

export interface ChatbotAlarmsProps {
  /** Resource name prefix */
  readonly prefix: string;
  /** Environment name */
  readonly envName: string;
  /** Chat Lambda function */
  readonly chatLambda: lambda.IFunction;
  /** Health Lambda function */
  readonly healthLambda: lambda.IFunction;
  /** API Gateway REST API */
  readonly api: apigateway.RestApi;
  /** SNS topic for alarm notifications */
  readonly alertTopic?: sns.ITopic;
  /** Chat Lambda log group for metric filters */
  readonly chatLogGroup?: logs.ILogGroup;
  /** Lambda error threshold (default: 5) */
  readonly lambdaErrorThreshold?: number;
  /** API Gateway 5XX error threshold (default: 10) */
  readonly api5xxThreshold?: number;
  /** API Gateway latency P99 threshold in ms (default: 10000) */
  readonly apiLatencyThreshold?: number;
  /** Guardrail violation threshold for alarm (default: 20) */
  readonly guardrailViolationThreshold?: number;
  /** Bedrock input-token alarm (#989). Omitted: no alarm. */
  readonly bedrockTokenAlarm?: BedrockTokenAlarmConfig;
}

/**
 * CloudWatch alarms for ChatbotStack monitoring.
 */
export class ChatbotAlarms extends Construct {
  public readonly chatLambdaErrorAlarm: cloudwatch.Alarm;
  public readonly chatLambdaDurationAlarm: cloudwatch.Alarm;
  public readonly api5xxAlarm: cloudwatch.Alarm;
  public readonly api4xxAlarm: cloudwatch.Alarm;
  public readonly apiLatencyAlarm: cloudwatch.Alarm;
  public readonly guardrailViolationAlarm?: cloudwatch.Alarm;
  public readonly hybridReleaseMismatchAlarm?: cloudwatch.Alarm;
  public readonly bedrockTokenAlarm?: cloudwatch.Alarm;

  constructor(scope: Construct, id: string, props: ChatbotAlarmsProps) {
    super(scope, id);

    const {
      prefix,
      envName,
      chatLambda,
      api,
      alertTopic,
      lambdaErrorThreshold = 5,
      api5xxThreshold = 10,
      apiLatencyThreshold = 10000,
    } = props;

    this.chatLambdaErrorAlarm = new cloudwatch.Alarm(
      this,
      'ChatLambdaErrorAlarm',
      {
        alarmName: `${prefix}-chat-lambda-errors-${envName}`,
        alarmDescription: `Chat Lambda errors exceed ${lambdaErrorThreshold} in 5 minutes. Runbook: docs/runbooks/maintenance_mode.md`,
        metric: chatLambda.metricErrors({
          period: cdk.Duration.minutes(5),
          statistic: cloudwatch.Stats.SUM,
        }),
        threshold: lambdaErrorThreshold,
        evaluationPeriods: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    this.chatLambdaDurationAlarm = new cloudwatch.Alarm(
      this,
      'ChatLambdaDurationAlarm',
      {
        alarmName: `${prefix}-chat-lambda-duration-${envName}`,
        alarmDescription:
          'Chat Lambda duration approaching timeout (>22.4s). Runbook: docs/runbooks/maintenance_mode.md',
        metric: chatLambda.metricDuration({
          period: cdk.Duration.minutes(5),
          statistic: cloudwatch.Stats.MAXIMUM,
        }),
        threshold: 22400, // 80% of 28s Lambda timeout
        evaluationPeriods: 2,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    this.api5xxAlarm = new cloudwatch.Alarm(this, 'Api5xxAlarm', {
      alarmName: `${prefix}-api-5xx-errors-${envName}`,
      alarmDescription: `API Gateway 5XX errors exceed ${api5xxThreshold} in 5 minutes. Runbook: docs/runbooks/maintenance_mode.md`,
      metric: api.metricServerError({
        period: cdk.Duration.minutes(5),
        statistic: cloudwatch.Stats.SUM,
      }),
      threshold: api5xxThreshold,
      evaluationPeriods: 1,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    this.api4xxAlarm = new cloudwatch.Alarm(this, 'Api4xxAlarm', {
      alarmName: `${prefix}-api-4xx-errors-${envName}`,
      alarmDescription: 'API Gateway 4XX errors exceed 50 in 5 minutes',
      metric: api.metricClientError({
        period: cdk.Duration.minutes(5),
        statistic: cloudwatch.Stats.SUM,
      }),
      threshold: 50,
      evaluationPeriods: 2,
      comparisonOperator:
        cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    this.apiLatencyAlarm = new cloudwatch.Alarm(this, 'ApiLatencyAlarm', {
      alarmName: `${prefix}-api-latency-p99-${envName}`,
      alarmDescription: `API Gateway P99 latency exceeds ${apiLatencyThreshold}ms`,
      metric: api.metricLatency({
        period: cdk.Duration.minutes(5),
        statistic: 'p99',
      }),
      threshold: apiLatencyThreshold,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    if (props.chatLogGroup) {
      const guardrailViolationThreshold =
        props.guardrailViolationThreshold || 20;

      const metricFilter = new logs.MetricFilter(
        this,
        'GuardrailViolationMetricFilter',
        {
          logGroup: props.chatLogGroup,
          filterPattern: logs.FilterPattern.literal(
            '"guardrail_category" -"ALLOW"',
          ),
          metricNamespace: `${prefix}/${envName}`,
          metricName: 'GuardrailViolations',
          metricValue: '1',
          defaultValue: 0,
        },
      );

      this.guardrailViolationAlarm = new cloudwatch.Alarm(
        this,
        'GuardrailViolationAlarm',
        {
          alarmName: `${prefix}-guardrail-violations-${envName}`,
          alarmDescription: `Guardrail violations exceed ${guardrailViolationThreshold} in 5 minutes (potential abuse)`,
          metric: metricFilter.metric({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.SUM,
          }),
          threshold: guardrailViolationThreshold,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    // Any BM25 failure (including a vector/BM25 release_id mismatch) is a
    // coherence regression — threshold 1, since it should be unreachable after
    // a coherent promotion. Monitoring-only: does NOT change the runtime's
    // fail-open-to-semantic-only behavior.
    if (props.chatLogGroup) {
      const hybridMismatchThreshold = 1;

      const mismatchMetricFilter = new logs.MetricFilter(
        this,
        'HybridReleaseMismatchMetricFilter',
        {
          logGroup: props.chatLogGroup,
          filterPattern: logs.FilterPattern.literal(
            '"BM25 search failed, using semantic-only"',
          ),
          metricNamespace: `${prefix}/${envName}`,
          metricName: 'HybridReleaseMismatch',
          metricValue: '1',
          defaultValue: 0,
        },
      );

      this.hybridReleaseMismatchAlarm = new cloudwatch.Alarm(
        this,
        'HybridReleaseMismatchAlarm',
        {
          alarmName: `${prefix}-hybrid-release-mismatch-${envName}`,
          alarmDescription:
            'A BM25 retrieval call failed (including a vector/BM25 ' +
            'release_id mismatch) and the request degraded to semantic-only. ' +
            'See docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md',
          metric: mismatchMetricFilter.metric({
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.SUM,
          }),
          threshold: hybridMismatchThreshold,
          evaluationPeriods: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    // #989: Early signal for cost abuse, also when many IPs each stay under
    // the per-IP WAF limit. Detection only: the automatic brake stays
    // budget pacing (#579); the alarm does not switch maintenance mode.
    if (props.bedrockTokenAlarm) {
      const {
        modelId,
        thresholdPer5Min,
        evaluationPeriods = 3,
      } = props.bedrockTokenAlarm;

      this.bedrockTokenAlarm = new cloudwatch.Alarm(
        this,
        'BedrockInputTokenAlarm',
        {
          alarmName: `${prefix}-bedrock-input-tokens-${envName}`,
          alarmDescription:
            `Bedrock InputTokenCount of ${modelId} above ` +
            `${thresholdPer5Min} per 5 minutes in ${evaluationPeriods} ` +
            'consecutive periods (possible cost abuse). ' +
            'Runbook: docs/runbooks/token_alarm.md',
          metric: new cloudwatch.Metric({
            namespace: 'AWS/Bedrock',
            metricName: 'InputTokenCount',
            dimensionsMap: { ModelId: modelId },
            period: cdk.Duration.minutes(5),
            statistic: cloudwatch.Stats.SUM,
          }),
          threshold: thresholdPer5Min,
          evaluationPeriods,
          datapointsToAlarm: evaluationPeriods,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          // No traffic means no tokens, not a broken metric.
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
    }

    if (alertTopic) {
      const snsAction = new actions.SnsAction(alertTopic);
      this.chatLambdaErrorAlarm.addAlarmAction(snsAction);
      this.chatLambdaDurationAlarm.addAlarmAction(snsAction);
      this.api5xxAlarm.addAlarmAction(snsAction);
      this.apiLatencyAlarm.addAlarmAction(snsAction);
      if (this.guardrailViolationAlarm) {
        this.guardrailViolationAlarm.addAlarmAction(snsAction);
      }
      if (this.hybridReleaseMismatchAlarm) {
        this.hybridReleaseMismatchAlarm.addAlarmAction(snsAction);
      }
      if (this.bedrockTokenAlarm) {
        this.bedrockTokenAlarm.addAlarmAction(snsAction);
      }
      // 4XX is warning-level, not adding to SNS by default
    }
  }
}
