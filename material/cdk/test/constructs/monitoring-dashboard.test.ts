import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sqs from 'aws-cdk-lib/aws-sqs';

import { MonitoringDashboard } from '../../lib/constructs/monitoring/monitoring-dashboard';

function baseStack(): Stack {
  const app = new App();
  return new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
}

function dummyLambda(stack: Stack, id: string): lambda.Function {
  return new lambda.Function(stack, id, {
    runtime: lambda.Runtime.NODEJS_20_X,
    handler: 'index.handler',
    code: lambda.Code.fromInline('exports.handler = async () => {};'),
  });
}

function dummyApi(stack: Stack): apigateway.RestApi {
  const api = new apigateway.RestApi(stack, 'Api');
  api.root.addMethod('GET');
  return api;
}

// DashboardBody is a CFN Fn::Join over literal string chunks and {Ref: ...}
// tokens; widget titles / metric names never contain tokens, so flattening the
// string parts gives a token-layout-independent way to assert a widget exists.
function dashboardBodyText(template: Template): string {
  const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
  const [dashboard] = Object.values(dashboards) as any[];
  const parts: unknown[] = dashboard.Properties.DashboardBody['Fn::Join'][1];
  return parts.filter((p) => typeof p === 'string').join('');
}

describe('MonitoringDashboard', () => {
  test('base construction: no BM25/retrieval-health widgets without those props', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);

    new MonitoringDashboard(stack, 'Dashboard', {
      prefix: 'renate',
      envName: 'dev',
      chatLambda,
      healthLambda,
      api,
    });

    const body = dashboardBodyText(Template.fromStack(stack));
    expect(body).toContain('System Health Overview');
    expect(body).not.toContain('BM25 Builder');
    expect(body).not.toContain('BM25 Rebuild');
    expect(body).not.toContain('Retrieval Health');
  });

  test('#494: BM25 builder widgets render when bm25BuilderLambda is provided', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);
    const bm25BuilderLambda = dummyLambda(stack, 'Bm25Builder');

    new MonitoringDashboard(stack, 'Dashboard', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
      bm25BuilderLambda,
    });

    const body = dashboardBodyText(Template.fromStack(stack));
    expect(body).toContain('BM25 Builder Invocations & Errors');
    expect(body).toContain('BM25 Builder Duration (P95)');
    expect(body).not.toContain('BM25 Rebuild Queue Depth');
    expect(body).not.toContain('BM25 Rebuild DLQ Depth');
  });

  test('#494: BM25 rebuild queue/DLQ depth widgets render independently of the builder Lambda widget', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);
    const bm25RebuildQueue = new sqs.Queue(stack, 'Bm25RebuildQueue');
    const bm25RebuildDlq = new sqs.Queue(stack, 'Bm25RebuildDlq');

    new MonitoringDashboard(stack, 'Dashboard', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
      bm25RebuildQueue,
      bm25RebuildDlq,
    });

    const body = dashboardBodyText(Template.fromStack(stack));
    expect(body).toContain('BM25 Rebuild Queue Depth');
    expect(body).toContain('BM25 Rebuild DLQ Depth');
    expect(body).not.toContain('BM25 Builder Invocations');
  });

  test('#494: Retrieval Health row renders only when showRetrievalHealthMetrics is true', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);

    new MonitoringDashboard(stack, 'Dashboard', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
      showRetrievalHealthMetrics: true,
    });

    const template = Template.fromStack(stack);
    const body = dashboardBodyText(template);
    expect(body).toContain('Retrieval Health');

    const dashboards = template.findResources('AWS::CloudWatch::Dashboard');
    const [dashboard] = Object.values(dashboards) as any[];
    const raw = JSON.stringify(dashboard.Properties.DashboardBody);
    for (const metricName of [
      'IngestionFailure',
      'CoherenceFailure',
      'RetentionPinMissing',
      'CheckExecuted',
    ]) {
      expect(raw).toContain(metricName);
    }
    expect(raw).toContain('Renate/QA/Retrieval');
  });

  test('#494: showRetrievalHealthMetrics defaults to off (dev/preprod/prod stay clean)', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);

    new MonitoringDashboard(stack, 'Dashboard', {
      prefix: 'renate',
      envName: 'dev',
      chatLambda,
      healthLambda,
      api,
    });

    const body = dashboardBodyText(Template.fromStack(stack));
    expect(body).not.toContain('Retrieval Health');
    expect(body).not.toContain('Renate/QA/Retrieval');
  });
});
