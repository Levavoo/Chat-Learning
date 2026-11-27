import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface MonitoringDashboardProps {
  /** Resource name prefix */
  readonly prefix: string;
  /** Environment name */
  readonly envName: string;
  /** Chat Lambda function */
  readonly chatLambda: lambda.IFunction;
  /** Health Lambda function */
  readonly healthLambda: lambda.IFunction;
  /** Transform Lambda function (optional) */
  readonly transformLambda?: lambda.IFunction;
  /** API Gateway */
  readonly api: apigateway.RestApi;
  /** Chatbot SQS Queue (optional) */
  readonly chatbotQueue?: sqs.IQueue;
  /** ETL SQS Queue (optional) */
  readonly etlQueue?: sqs.IQueue;
  /** ETL DLQ (optional) */
  readonly etlDlq?: sqs.IQueue;
  /** BM25 index builder Lambda (optional) */
  readonly bm25BuilderLambda?: lambda.IFunction;
  /** BM25 rebuild queue (optional) */
  readonly bm25RebuildQueue?: sqs.IQueue;
  /** BM25 rebuild DLQ (optional) */
  readonly bm25RebuildDlq?: sqs.IQueue;
  /**
   * Show the "Retrieval Health" single-value row for the scheduled health
   * check's custom metrics. Separate from the BM25 widgets because a heartbeat
   * row is valid only after an environment's scheduled publisher is enabled.
   */
  readonly showRetrievalHealthMetrics?: boolean;
  /** Namespace used by retrieval-health custom metrics when the row is shown. */
  readonly retrievalHealthMetricNamespace?: string;
  /** CloudFront Distribution ID (optional) */
  readonly distributionId?: string;
  /** Knowledge Base ID (optional) */
  readonly knowledgeBaseId?: string;
  /** Bedrock Model ID (optional) */
  readonly bedrockModelId?: string;
  /** DynamoDB conversation table name (optional, for consumed capacity widgets) */
  readonly conversationTableName?: string;
  /** CloudWatch Alarms to display in the alarm status widget */
  readonly alarms?: cloudwatch.IAlarm[];
}

/**
 * Unified CloudWatch Dashboard for the application.
 * Displays key metrics for Lambda, API Gateway, SQS, Bedrock, and CloudFront.
 */
export class MonitoringDashboard extends Construct {
  public readonly dashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: MonitoringDashboardProps) {
    super(scope, id);

    const {
      prefix,
      envName,
      chatLambda,
      healthLambda,
      transformLambda,
      api,
      etlQueue,
      etlDlq,
      bm25BuilderLambda,
      bm25RebuildQueue,
      bm25RebuildDlq,
      showRetrievalHealthMetrics,
      retrievalHealthMetricNamespace,
      distributionId,
      bedrockModelId,
      conversationTableName,
    } = props;

    this.dashboard = new cloudwatch.Dashboard(this, 'Dashboard', {
      dashboardName: `${prefix}-monitoring-${envName}`,
      defaultInterval: cdk.Duration.hours(3),
    });

    if (props.alarms && props.alarms.length > 0) {
      this.dashboard.addWidgets(
        new cloudwatch.AlarmStatusWidget({
          title: 'Alarm Status',
          width: 24,
          height: 3,
          alarms: props.alarms,
        }),
      );
    }

    this.dashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: 'System Health Overview',
        width: 24,
        height: 4,
        metrics: [
          api.metricServerError({
            period: cdk.Duration.minutes(1),
            statistic: cloudwatch.Stats.SUM,
            label: 'API 5XX',
          }),
          api.metricClientError({
            period: cdk.Duration.minutes(1),
            statistic: cloudwatch.Stats.SUM,
            label: 'API 4XX',
          }),
          chatLambda.metricErrors({
            period: cdk.Duration.minutes(1),
            statistic: cloudwatch.Stats.SUM,
            label: 'Chat Errors',
          }),
          ...(transformLambda
            ? [
                transformLambda.metricErrors({
                  period: cdk.Duration.minutes(1),
                  statistic: cloudwatch.Stats.SUM,
                  label: 'ETL Errors',
                }),
              ]
            : []),
        ],
      }),
    );

    const lambdaWidgets: cloudwatch.IWidget[] = [
      new cloudwatch.GraphWidget({
        title: 'Lambda Invocations',
        width: 8,
        height: 6,
        left: [
          chatLambda.metricInvocations({ label: 'Chat' }),
          healthLambda.metricInvocations({ label: 'Health' }),
          ...(transformLambda
            ? [
                transformLambda.metricInvocations({
                  label: 'Extract/Transform',
                }),
              ]
            : []),
        ],
        stacked: true,
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda Duration (P95)',
        width: 8,
        height: 6,
        left: [
          chatLambda.metricDuration({ statistic: 'p95', label: 'Chat' }),
          healthLambda.metricDuration({ statistic: 'p95', label: 'Health' }),
          ...(transformLambda
            ? [
                transformLambda.metricDuration({
                  statistic: 'p95',
                  label: 'ETL',
                }),
              ]
            : []),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda Errors & Throttles',
        width: 8,
        height: 6,
        left: [
          chatLambda.metricErrors({ label: 'Chat Errors', color: '#d62728' }),
          chatLambda.metricThrottles({
            label: 'Chat Throttles',
            color: '#ff7f0e',
          }),
          ...(transformLambda
            ? [
                transformLambda.metricErrors({
                  label: 'ETL Errors',
                  color: '#9467bd',
                }),
              ]
            : []),
        ],
      }),
    ];
    this.dashboard.addWidgets(...lambdaWidgets);

    const apiWidgets: cloudwatch.IWidget[] = [
      new cloudwatch.GraphWidget({
        title: 'API Request Count',
        width: 8,
        height: 6,
        left: [
          api.metricCount({
            period: cdk.Duration.minutes(1),
            statistic: cloudwatch.Stats.SUM,
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'API Latency (P95)',
        width: 8,
        height: 6,
        left: [api.metricLatency({ statistic: 'p95' })],
      }),
    ];

    if (distributionId) {
      apiWidgets.push(
        new cloudwatch.GraphWidget({
          title: 'CloudFront Requests',
          width: 8,
          height: 6,
          left: [
            new cloudwatch.Metric({
              namespace: 'AWS/CloudFront',
              metricName: 'Requests',
              dimensionsMap: {
                DistributionId: distributionId,
                Region: 'Global',
              },
              statistic: cloudwatch.Stats.SUM,
            }),
          ],
        }),
      );
    }
    this.dashboard.addWidgets(...apiWidgets);

    if (etlQueue || etlDlq) {
      const queueWidgets: cloudwatch.IWidget[] = [];

      if (etlQueue) {
        queueWidgets.push(
          new cloudwatch.GraphWidget({
            title: 'ETL Queue Depth',
            width: 12,
            height: 6,
            left: [
              etlQueue.metricApproximateNumberOfMessagesVisible({
                label: 'Visible Messages',
                period: cdk.Duration.minutes(1),
              }),
              etlQueue.metricNumberOfMessagesSent({
                label: 'Incoming Messages',
                period: cdk.Duration.minutes(1),
              }),
            ],
          }),
        );
      }

      if (etlDlq) {
        queueWidgets.push(
          new cloudwatch.GraphWidget({
            title: 'Dead Letter Queue Depth',
            width: 12,
            height: 6,
            left: [
              etlDlq.metricApproximateNumberOfMessagesVisible({
                label: 'DLQ Messages',
                color: '#d62728',
                period: cdk.Duration.minutes(1),
              }),
            ],
          }),
        );
      }
      this.dashboard.addWidgets(...queueWidgets);
    }

    if (bm25BuilderLambda) {
      this.dashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: 'BM25 Builder Invocations & Errors',
          width: 12,
          height: 6,
          left: [
            bm25BuilderLambda.metricInvocations({
              label: 'Invocations',
              period: cdk.Duration.minutes(5),
            }),
          ],
          right: [
            bm25BuilderLambda.metricErrors({
              label: 'Errors',
              color: '#d62728',
              period: cdk.Duration.minutes(5),
            }),
          ],
        }),
        new cloudwatch.GraphWidget({
          title: 'BM25 Builder Duration (P95)',
          width: 12,
          height: 6,
          left: [
            bm25BuilderLambda.metricDuration({
              statistic: 'p95',
              period: cdk.Duration.minutes(5),
            }),
          ],
        }),
      );
    }

    if (bm25RebuildQueue || bm25RebuildDlq) {
      const bm25QueueWidgets: cloudwatch.IWidget[] = [];

      if (bm25RebuildQueue) {
        bm25QueueWidgets.push(
          new cloudwatch.GraphWidget({
            title: 'BM25 Rebuild Queue Depth',
            width: 12,
            height: 6,
            left: [
              bm25RebuildQueue.metricApproximateNumberOfMessagesVisible({
                label: 'Visible Messages',
                period: cdk.Duration.minutes(1),
              }),
            ],
          }),
        );
      }

      if (bm25RebuildDlq) {
        bm25QueueWidgets.push(
          new cloudwatch.GraphWidget({
            title: 'BM25 Rebuild DLQ Depth',
            width: 12,
            height: 6,
            left: [
              bm25RebuildDlq.metricApproximateNumberOfMessagesVisible({
                label: 'DLQ Messages',
                color: '#d62728',
                period: cdk.Duration.minutes(1),
              }),
            ],
          }),
        );
      }
      this.dashboard.addWidgets(...bm25QueueWidgets);
    }

    if (showRetrievalHealthMetrics) {
      const retrievalHealthMetric = (metricName: string, label: string) =>
        new cloudwatch.Metric({
          namespace: retrievalHealthMetricNamespace ?? 'Renate/QA/Retrieval',
          metricName,
          label,
          period: cdk.Duration.minutes(15),
          statistic: cloudwatch.Stats.MAXIMUM,
        });

      this.dashboard.addWidgets(
        new cloudwatch.SingleValueWidget({
          title: 'Retrieval Health',
          width: 24,
          height: 4,
          metrics: [
            retrievalHealthMetric('IngestionFailure', 'Ingestion Failure'),
            retrievalHealthMetric('CoherenceFailure', 'Coherence Failure'),
            retrievalHealthMetric(
              'RetentionPinMissing',
              'Retention Pin Missing',
            ),
            new cloudwatch.Metric({
              namespace:
                retrievalHealthMetricNamespace ?? 'Renate/QA/Retrieval',
              metricName: 'CheckExecuted',
              label: 'Check Executed (heartbeat)',
              period: cdk.Duration.minutes(15),
              statistic: cloudwatch.Stats.SUM,
            }),
          ],
        }),
      );
    }

    if (bedrockModelId) {
      this.dashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: 'Bedrock Token Usage',
          width: 12,
          height: 6,
          left: [
            new cloudwatch.Metric({
              namespace: 'AWS/Bedrock',
              metricName: 'InputTokenCount',
              dimensionsMap: { ModelId: bedrockModelId },
              statistic: cloudwatch.Stats.SUM,
              label: 'Input Tokens',
            }),
            new cloudwatch.Metric({
              namespace: 'AWS/Bedrock',
              metricName: 'OutputTokenCount',
              dimensionsMap: { ModelId: bedrockModelId },
              statistic: cloudwatch.Stats.SUM,
              label: 'Output Tokens',
            }),
          ],
        }),
        new cloudwatch.GraphWidget({
          title: 'Bedrock Invocations & Errors',
          width: 12,
          height: 6,
          left: [
            new cloudwatch.Metric({
              namespace: 'AWS/Bedrock',
              metricName: 'Invocations',
              dimensionsMap: { ModelId: bedrockModelId },
              statistic: cloudwatch.Stats.SUM,
              label: 'Invocations',
            }),
          ],
          right: [
            new cloudwatch.Metric({
              namespace: 'AWS/Bedrock',
              metricName: 'InvocationClientErrors',
              dimensionsMap: { ModelId: bedrockModelId },
              statistic: cloudwatch.Stats.SUM,
              label: 'Client Errors',
              color: '#ff7f0e',
            }),
            new cloudwatch.Metric({
              namespace: 'AWS/Bedrock',
              metricName: 'InvocationServerErrors',
              dimensionsMap: { ModelId: bedrockModelId },
              statistic: cloudwatch.Stats.SUM,
              label: 'Server Errors',
              color: '#d62728',
            }),
          ],
        }),
      );
    }

    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Lambda Concurrent Executions',
        width: 8,
        height: 6,
        left: [
          chatLambda.metric('ConcurrentExecutions', {
            statistic: cloudwatch.Stats.MAXIMUM,
            label: 'Chat Max Concurrent',
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'NAT Gateway Traffic',
        width: 8,
        height: 6,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/NATGateway',
            metricName: 'BytesOutToDestination',
            statistic: cloudwatch.Stats.SUM,
            label: 'Bytes Out',
          }),
        ],
        right: [
          new cloudwatch.Metric({
            namespace: 'AWS/NATGateway',
            metricName: 'PacketsDropCount',
            statistic: cloudwatch.Stats.SUM,
            label: 'Packets Dropped',
            color: '#d62728',
          }),
        ],
      }),
      ...(conversationTableName
        ? [
            new cloudwatch.GraphWidget({
              title: 'DynamoDB Consumed Capacity',
              width: 8,
              height: 6,
              left: [
                new cloudwatch.Metric({
                  namespace: 'AWS/DynamoDB',
                  metricName: 'ConsumedReadCapacityUnits',
                  dimensionsMap: { TableName: conversationTableName },
                  statistic: cloudwatch.Stats.SUM,
                  label: 'Read CU',
                }),
                new cloudwatch.Metric({
                  namespace: 'AWS/DynamoDB',
                  metricName: 'ConsumedWriteCapacityUnits',
                  dimensionsMap: { TableName: conversationTableName },
                  statistic: cloudwatch.Stats.SUM,
                  label: 'Write CU',
                  color: '#ff7f0e',
                }),
              ],
            }),
          ]
        : []),
    );
  }
}
