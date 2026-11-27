import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import * as s3 from 'aws-cdk-lib/aws-s3';

import { KbSyncTrigger } from '../../lib/constructs/knowledge-base/kb-sync-trigger';

function buildTemplate(): Template {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  const bucket = new s3.Bucket(stack, 'IngestionBucket');

  new KbSyncTrigger(stack, 'KbSyncTrigger', {
    ingestionBucket: bucket,
    knowledgeBaseId: 'kb-abc123',
    dataSourceId: 'ds-xyz789',
    prefix: 'docs/',
    suffixes: ['.json'],
  });

  return Template.fromStack(stack);
}

describe('KbSyncTrigger', () => {
  test('adds both ObjectCreated and ObjectRemoved notifications to ingestion bucket', () => {
    const template = buildTemplate();

    const notifications = template.findResources(
      'Custom::S3BucketNotifications',
    );
    const allNotifProps = Object.values(notifications).flatMap((n: any) =>
      n.Properties?.NotificationConfiguration
        ? [n.Properties.NotificationConfiguration]
        : [],
    );

    const lambdaConfigs = allNotifProps.flatMap(
      (cfg: any) => cfg.LambdaFunctionConfigurations ?? [],
    );
    const events = lambdaConfigs.flatMap((c: any) => c.Events ?? []);

    expect(events).toContain('s3:ObjectCreated:*');
    expect(events).toContain('s3:ObjectRemoved:*');
  });
});
