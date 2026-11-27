import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';

import { ChatbotAlarms } from '../../lib/constructs/monitoring/chatbot-alarms';

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

describe('ChatbotAlarms', () => {
  test('base construction: chat/health/API alarms are created without a log group', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);

    new ChatbotAlarms(stack, 'ChatbotAlarms', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
    });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    expect(alarmNames).toContain('renate-chat-lambda-errors-qa');
    expect(alarmNames).toContain('renate-chat-lambda-duration-qa');
    expect(alarmNames).toContain('renate-api-5xx-errors-qa');
    expect(alarmNames).toContain('renate-api-4xx-errors-qa');
    expect(alarmNames).toContain('renate-api-latency-p99-qa');
    // No log group ⇒ no guardrail or hybrid-mismatch alarms.
    expect(
      alarmNames.some((n: string) => n?.includes('guardrail-violations')),
    ).toBe(false);
    expect(
      alarmNames.some((n: string) => n?.includes('hybrid-release-mismatch')),
    ).toBe(false);
  });

  test('#494: hybrid release mismatch metric filter + alarm are created when chatLogGroup is present', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);
    const logGroup = new logs.LogGroup(stack, 'ChatLogGroup');

    new ChatbotAlarms(stack, 'ChatbotAlarms', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
      chatLogGroup: logGroup,
    });

    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Logs::MetricFilter', {
      FilterPattern: '"BM25 search failed, using semantic-only"',
      MetricTransformations: Match.arrayWith([
        Match.objectLike({
          MetricName: 'HybridReleaseMismatch',
          MetricNamespace: 'renate/qa',
          MetricValue: '1',
          DefaultValue: 0,
        }),
      ]),
    });

    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    expect(alarmNames).toContain('renate-hybrid-release-mismatch-qa');

    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'renate-hybrid-release-mismatch-qa',
      Threshold: 1,
      EvaluationPeriods: 1,
      ComparisonOperator: 'GreaterThanOrEqualToThreshold',
      TreatMissingData: 'notBreaching',
    });
  });

  test('#989: no token alarm without bedrockTokenAlarm config', () => {
    const stack = baseStack();
    new ChatbotAlarms(stack, 'ChatbotAlarms', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda: dummyLambda(stack, 'ChatLambda'),
      healthLambda: dummyLambda(stack, 'HealthLambda'),
      api: dummyApi(stack),
    });
    const alarms = Template.fromStack(stack).findResources(
      'AWS::CloudWatch::Alarm',
    );
    expect(
      Object.values(alarms).some(
        (a: any) => a.Properties?.MetricName === 'InputTokenCount',
      ),
    ).toBe(false);
  });

  test('#989: token alarm sums InputTokenCount of one model, 3 of 3, to SNS', () => {
    const stack = baseStack();
    const topic = new sns.Topic(stack, 'AlertTopic');
    new ChatbotAlarms(stack, 'ChatbotAlarms', {
      prefix: 'renate',
      envName: 'prod',
      chatLambda: dummyLambda(stack, 'ChatLambda'),
      healthLambda: dummyLambda(stack, 'HealthLambda'),
      api: dummyApi(stack),
      alertTopic: topic,
      bedrockTokenAlarm: {
        modelId: 'openai.gpt-oss-120b-1:0',
        thresholdPer5Min: 1_500_000,
      },
    });
    Template.fromStack(stack).hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'renate-bedrock-input-tokens-prod',
      Namespace: 'AWS/Bedrock',
      MetricName: 'InputTokenCount',
      Dimensions: [{ Name: 'ModelId', Value: 'openai.gpt-oss-120b-1:0' }],
      Statistic: 'Sum',
      Period: 300,
      Threshold: 1_500_000,
      EvaluationPeriods: 3,
      DatapointsToAlarm: 3,
      ComparisonOperator: 'GreaterThanThreshold',
      TreatMissingData: 'notBreaching',
      AlarmActions: [{ Ref: Match.stringLikeRegexp('AlertTopic') }],
    });
  });

  test('#494: hybrid mismatch alarm routes to the SNS alert topic when provided', () => {
    const stack = baseStack();
    const chatLambda = dummyLambda(stack, 'ChatLambda');
    const healthLambda = dummyLambda(stack, 'HealthLambda');
    const api = dummyApi(stack);
    const logGroup = new logs.LogGroup(stack, 'ChatLogGroup');
    const topic = new sns.Topic(stack, 'AlertTopic');

    new ChatbotAlarms(stack, 'ChatbotAlarms', {
      prefix: 'renate',
      envName: 'qa',
      chatLambda,
      healthLambda,
      api,
      chatLogGroup: logGroup,
      alertTopic: topic,
    });

    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'renate-hybrid-release-mismatch-qa',
      AlarmActions: Match.arrayWith([
        { Ref: Match.stringLikeRegexp('AlertTopic') },
      ]),
    });
  });
});
