import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';

import { TransformPipeline } from '../../lib/constructs/knowledge-base/transform-pipeline';
import { EtlConfig } from '../../lib/config/kb/etl-config';

const testEtlConfig: EtlConfig = {
  lambdaTimeoutSeconds: 300,
  lambdaMemorySizeMb: 1024,
  batchSize: 10,
  batchWindowSeconds: 30,
  visibilityTimeoutSeconds: 360,
  messageRetentionDays: 4,
  maxReceiveCount: 3,
};

function buildTemplate(prefix?: string, suffix?: string): Template {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  const sourceBucket = new s3.Bucket(stack, 'SourceBucket');
  const destBucket = new s3.Bucket(stack, 'DestBucket');
  const etlRepo = ecr.Repository.fromRepositoryAttributes(stack, 'EtlRepo', {
    repositoryName: 'renate-etl-lambda',
    repositoryArn:
      'arn:aws:ecr:eu-central-1:831926590742:repository/renate-etl-lambda',
  });

  new TransformPipeline(stack, 'Pipeline', {
    etlConfig: testEtlConfig,
    sourceBucket,
    destinationBucket: destBucket,
    sourcePrefix: prefix,
    sourceSuffix: suffix,
    etlRepo,
    etlImageTag: 'v1.2.3',
  });

  return Template.fromStack(stack);
}

describe('TransformPipeline', () => {
  describe('IAM policy', () => {
    test('grants s3:DeleteObject on destination bucket', () => {
      const template = buildTemplate();
      template.hasResourceProperties('AWS::IAM::Role', {
        Policies: Match.arrayWith([
          Match.objectLike({
            PolicyDocument: {
              Statement: Match.arrayWith([
                Match.objectLike({
                  Action: 's3:DeleteObject',
                  Effect: 'Allow',
                }),
              ]),
            },
          }),
        ]),
      });
    });
  });

  describe('S3 notifications without filter', () => {
    test('adds ObjectCreated and ObjectRemoved notifications to source bucket', () => {
      const template = buildTemplate();

      const notifications = template.findResources(
        'Custom::S3BucketNotifications',
      );
      const allNotifProps = Object.values(notifications).flatMap((n: any) =>
        n.Properties?.NotificationConfiguration
          ? [n.Properties.NotificationConfiguration]
          : [],
      );

      const queueConfigs = allNotifProps.flatMap(
        (cfg: any) => cfg.QueueConfigurations ?? [],
      );
      const events = queueConfigs.flatMap((q: any) => q.Events ?? []);

      expect(events).toContain('s3:ObjectCreated:*');
      expect(events).toContain('s3:ObjectRemoved:*');
    });
  });

  describe('S3 notifications with filter', () => {
    test('both notifications carry matching prefix filter', () => {
      const template = buildTemplate('IN/', '.xml');

      const notifications = template.findResources(
        'Custom::S3BucketNotifications',
      );
      const allNotifProps = Object.values(notifications).flatMap((n: any) =>
        n.Properties?.NotificationConfiguration
          ? [n.Properties.NotificationConfiguration]
          : [],
      );
      const queueConfigs = allNotifProps.flatMap(
        (cfg: any) => cfg.QueueConfigurations ?? [],
      );

      const createdWithFilter = queueConfigs.find(
        (q: any) =>
          (q.Events ?? []).includes('s3:ObjectCreated:*') &&
          q.Filter?.Key?.FilterRules?.some(
            (r: any) => r.Name === 'prefix' && r.Value === 'IN/',
          ),
      );
      const removedWithFilter = queueConfigs.find(
        (q: any) =>
          (q.Events ?? []).includes('s3:ObjectRemoved:*') &&
          q.Filter?.Key?.FilterRules?.some(
            (r: any) => r.Name === 'prefix' && r.Value === 'IN/',
          ),
      );

      expect(createdWithFilter).toBeDefined();
      expect(removedWithFilter).toBeDefined();
    });
  });

  describe('ECR image reference (#590 — fromImageAsset → fromEcr)', () => {
    test('Lambda function references the renate-etl-lambda ECR image URI', () => {
      const template = buildTemplate();
      template.hasResourceProperties('AWS::Lambda::Function', {
        Code: Match.objectLike({
          ImageUri: Match.objectLike({
            'Fn::Join': Match.arrayWith([
              '',
              Match.arrayWith([Match.stringLikeRegexp('renate-etl-lambda')]),
            ]),
          }),
        }),
      });
    });

    test('no local Docker asset (CDKMetadata asset entry) is produced for the transform Lambda', () => {
      // fromImageAsset would register an aws-cdk:asset entry pointing at a local
      // dockerBuildArgs/dockerfile path; fromEcr does not.
      const template = buildTemplate();
      const assembly = JSON.stringify(template.toJSON());
      expect(assembly).not.toContain('dockerfile');
    });
  });
});
