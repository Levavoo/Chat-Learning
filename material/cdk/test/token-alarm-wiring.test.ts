import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { Template } from 'aws-cdk-lib/assertions';

// #989: Runs the real entry point with the real parameter map, so a missing
// or wrong wiring in bin/infrastructure.ts shows up, not only in the construct.
function synthChatbot(envName: string): Template {
  const outdir = fs.mkdtempSync(path.join(os.tmpdir(), 'token-alarm-'));
  const saved = {
    ctx: process.env.CDK_CONTEXT_JSON,
    out: process.env.CDK_OUTDIR,
  };
  process.env.CDK_CONTEXT_JSON = JSON.stringify({
    env: envName,
    etlImageTag: 'v0.0.0',
    // Prod refuses to synth without these; irrelevant for the alarm.
    ...(envName === 'prod' && {
      retrievalCandidateSlot: 'blue',
      blueEtlImageTag: 'v0.0.0',
      greenEtlImageTag: 'v0.0.0',
    }),
  });
  process.env.CDK_OUTDIR = outdir;
  try {
    jest.isolateModules(() => {
      // The entry point runs on import; isolateModules needs require.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require('../bin/infrastructure');
    });
    return Template.fromJSON(
      JSON.parse(
        fs.readFileSync(
          path.join(outdir, `renate-chatbot-${envName}.template.json`),
          'utf8',
        ),
      ),
    );
  } finally {
    for (const [key, value] of [
      ['CDK_CONTEXT_JSON', saved.ctx],
      ['CDK_OUTDIR', saved.out],
    ] as const) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    fs.rmSync(outdir, { recursive: true, force: true });
  }
}

function tokenAlarms(template: Template): Array<Record<string, any>> {
  return Object.values(template.findResources('AWS::CloudWatch::Alarm'))
    .map((a: any) => a.Properties)
    .filter((p: any) => p.MetricName === 'InputTokenCount');
}

describe('Token alarm wiring (#989)', () => {
  test('prod: one alarm on gpt-oss with the measured values, action on renate-alerts-prod', () => {
    const template = synthChatbot('prod');
    const alarms = tokenAlarms(template);
    expect(alarms).toHaveLength(1);
    const alarm = alarms[0];
    expect(alarm).toMatchObject({
      AlarmName: 'renate-bedrock-input-tokens-prod',
      Namespace: 'AWS/Bedrock',
      Dimensions: [{ Name: 'ModelId', Value: 'openai.gpt-oss-120b-1:0' }],
      Statistic: 'Sum',
      Period: 300,
      Threshold: 1_500_000,
      EvaluationPeriods: 3,
      DatapointsToAlarm: 3,
      ComparisonOperator: 'GreaterThanThreshold',
    });

    // The action must point at the topic named renate-alerts-prod.
    const topics = template.findResources('AWS::SNS::Topic', {
      Properties: { TopicName: 'renate-alerts-prod' },
    });
    const topicIds = Object.keys(topics);
    expect(topicIds).toHaveLength(1);
    expect(alarm.AlarmActions).toEqual([{ Ref: topicIds[0] }]);

    const subscribers = Object.values(
      template.findResources('AWS::SNS::Subscription'),
    )
      .filter((s: any) => s.Properties.TopicArn?.Ref === topicIds[0])
      .map((s: any) => s.Properties.Endpoint)
      .sort();
    expect(subscribers).toEqual([
      'ki-reha-anwendungsbetrieb@drv-bund.de',
      'renate@drv-bund.de',
    ]);
  }, 300_000);

  test('dev: no token alarm', () => {
    expect(tokenAlarms(synthChatbot('dev'))).toHaveLength(0);
  }, 300_000);
});
