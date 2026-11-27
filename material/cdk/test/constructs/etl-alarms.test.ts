import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as sns from 'aws-cdk-lib/aws-sns';

import { EtlAlarms } from '../../lib/constructs/knowledge-base/etl-alarms';

function baseStack(): { app: App; stack: Stack } {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  return { app, stack };
}

function dummyLambda(stack: Stack, id: string): lambda.Function {
  return new lambda.Function(stack, id, {
    runtime: lambda.Runtime.NODEJS_20_X,
    handler: 'index.handler',
    code: lambda.Code.fromInline('exports.handler = async () => {};'),
  });
}

describe('EtlAlarms', () => {
  test('base construction: transform Lambda + DLQ alarms are created', () => {
    const { stack } = baseStack();
    const transformLambda = dummyLambda(stack, 'TransformLambda');
    const dlq = new sqs.Queue(stack, 'Dlq');

    new EtlAlarms(stack, 'EtlAlarms', { transformLambda, dlq });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    expect(alarmNames.some((n: string) => n?.includes('dlq-messages'))).toBe(
      true,
    );
    expect(alarmNames.some((n: string) => n?.includes('lambda-errors'))).toBe(
      true,
    );
    expect(alarmNames.some((n: string) => n?.includes('lambda-duration'))).toBe(
      true,
    );
  });

  test('omitting transformLambda/dlq synthesizes without those alarms (#494 green-slot BM25-only use case)', () => {
    const { stack } = baseStack();
    const bm25BuilderLambda = dummyLambda(stack, 'Bm25Builder');
    const bm25RebuildDlq = new sqs.Queue(stack, 'Bm25RebuildDlq');

    new EtlAlarms(stack, 'EtlAlarms', {
      bm25BuilderLambda,
      bm25RebuildDlq,
      slot: 'green',
    });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    // "dlq-messages" (transform-DLQ alarm's purpose string) is a
    // substring of "bm25-rebuild-dlq-messages" — match on the transform
    // alarm's exact prefix, not a loose substring, to avoid a false positive
    // against the BM25 rebuild DLQ alarm this test does expect to exist.
    expect(
      alarmNames.some((n: string) =>
        /(?<!bm25-rebuild-)dlq-messages/.test(n ?? ''),
      ),
    ).toBe(false);
    expect(alarmNames.some((n: string) => n?.includes('lambda-errors'))).toBe(
      false,
    );
    expect(alarmNames).toHaveLength(3);
  });

  test('#494: BM25 builder error/duration/rebuild-DLQ alarms are created when props are present', () => {
    const { stack } = baseStack();
    const transformLambda = dummyLambda(stack, 'TransformLambda');
    const dlq = new sqs.Queue(stack, 'Dlq');
    const bm25BuilderLambda = dummyLambda(stack, 'Bm25Builder');
    const bm25RebuildDlq = new sqs.Queue(stack, 'Bm25RebuildDlq');

    new EtlAlarms(stack, 'EtlAlarms', {
      transformLambda,
      dlq,
      bm25BuilderLambda,
      bm25RebuildDlq,
    });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-builder-errors')),
    ).toBe(true);
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-builder-duration')),
    ).toBe(true);
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-rebuild-dlq-messages')),
    ).toBe(true);
  });

  test('#494: omitting BM25 props synthesizes without BM25 alarms (backward compatible)', () => {
    const { stack } = baseStack();
    const transformLambda = dummyLambda(stack, 'TransformLambda');
    const dlq = new sqs.Queue(stack, 'Dlq');

    new EtlAlarms(stack, 'EtlAlarms', { transformLambda, dlq });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    expect(alarmNames.some((n: string) => n?.includes('bm25-builder'))).toBe(
      false,
    );
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-rebuild-dlq')),
    ).toBe(false);
  });

  test('#494: two EtlAlarms instances with different slot props do not collide on AlarmName (blue vs green)', () => {
    const { stack } = baseStack();
    const transformLambda = dummyLambda(stack, 'TransformLambda');
    const dlq = new sqs.Queue(stack, 'Dlq');
    const blueBuilder = dummyLambda(stack, 'BlueBm25Builder');
    const blueDlq = new sqs.Queue(stack, 'BlueBm25RebuildDlq');
    const greenBuilder = dummyLambda(stack, 'GreenBm25Builder');
    const greenDlq = new sqs.Queue(stack, 'GreenBm25RebuildDlq');

    new EtlAlarms(stack, 'EtlAlarms', {
      transformLambda,
      dlq,
      bm25BuilderLambda: blueBuilder,
      bm25RebuildDlq: blueDlq,
      slot: 'blue',
    });
    new EtlAlarms(stack, 'GreenEtlAlarms', {
      bm25BuilderLambda: greenBuilder,
      bm25RebuildDlq: greenDlq,
      slot: 'green',
    });

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    const uniqueNames = new Set(alarmNames);
    // A collision here would make CloudFormation reject the second alarm at deploy.
    expect(uniqueNames.size).toBe(alarmNames.length);
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-builder-errors-blue')),
    ).toBe(true);
    expect(
      alarmNames.some((n: string) => n?.includes('bm25-builder-errors-green')),
    ).toBe(true);
  });

  test('#494: BM25 alarms route to the SNS alert topic when provided', () => {
    const { stack } = baseStack();
    const bm25BuilderLambda = dummyLambda(stack, 'Bm25Builder');
    const bm25RebuildDlq = new sqs.Queue(stack, 'Bm25RebuildDlq');
    const topic = new sns.Topic(stack, 'AlertTopic');

    new EtlAlarms(stack, 'EtlAlarms', {
      bm25BuilderLambda,
      bm25RebuildDlq,
      alertTopic: topic,
    });

    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmActions: Match.arrayWith([
        { Ref: Match.stringLikeRegexp('AlertTopic') },
      ]),
    });
  });
});
