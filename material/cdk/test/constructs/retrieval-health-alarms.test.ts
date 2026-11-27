import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as sns from 'aws-cdk-lib/aws-sns';

import { RetrievalHealthAlarms } from '../../lib/constructs/monitoring/retrieval-health-alarms';

function baseStack(): Stack {
  const app = new App();
  return new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
}

describe('RetrievalHealthAlarms', () => {
  test('#494: creates all four alarms watching the Renate/QA/Retrieval namespace', () => {
    const stack = baseStack();

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {});

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    expect(Object.keys(alarms)).toHaveLength(4);

    for (const metricName of [
      'IngestionFailure',
      'CoherenceFailure',
      'RetentionPinMissing',
    ]) {
      template.hasResourceProperties('AWS::CloudWatch::Alarm', {
        Namespace: 'Renate/QA/Retrieval',
        MetricName: metricName,
        Threshold: 1,
        EvaluationPeriods: 1,
        ComparisonOperator: 'GreaterThanOrEqualToThreshold',
        TreatMissingData: 'notBreaching',
      });
    }
  });

  test('#494: CheckExecutedAlarm alarms on missing data (heartbeat), unlike the outcome alarms', () => {
    const stack = baseStack();

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {});

    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      Namespace: 'Renate/QA/Retrieval',
      MetricName: 'CheckExecuted',
      Threshold: 1,
      EvaluationPeriods: 3,
      ComparisonOperator: 'LessThanThreshold',
      TreatMissingData: 'breaching',
    });
  });

  test('#641: accepts an environment-specific metric namespace', () => {
    const stack = baseStack();

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {
      metricNamespace: 'Renate/Preprod/Retrieval',
    });

    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      Namespace: 'Renate/Preprod/Retrieval',
      MetricName: 'CheckExecuted',
    });
  });

  test('#494: alarm descriptions link the #494 runbook', () => {
    const stack = baseStack();

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {});

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const descriptions = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmDescription,
    );
    for (const description of descriptions) {
      expect(description).toContain(
        'docs/architecture/runbooks/494-retrieval-monitoring-and-alarms.md',
      );
    }
  });

  test('#494: all four alarms route to the SNS alert topic when provided', () => {
    const stack = baseStack();
    const topic = new sns.Topic(stack, 'AlertTopic');

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {
      alertTopic: topic,
    });

    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      MetricName: 'IngestionFailure',
      AlarmActions: Match.arrayWith([
        { Ref: Match.stringLikeRegexp('AlertTopic') },
      ]),
    });
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      MetricName: 'CheckExecuted',
      AlarmActions: Match.arrayWith([
        { Ref: Match.stringLikeRegexp('AlertTopic') },
      ]),
    });
  });

  test('#494: without an alert topic, no alarm has AlarmActions', () => {
    const stack = baseStack();

    new RetrievalHealthAlarms(stack, 'RetrievalHealthAlarms', {});

    const template = Template.fromStack(stack);
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    for (const alarm of Object.values(alarms) as any[]) {
      expect(alarm.Properties?.AlarmActions ?? []).toHaveLength(0);
    }
  });
});
