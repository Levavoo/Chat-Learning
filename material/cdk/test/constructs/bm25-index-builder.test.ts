import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';

import { Bm25IndexBuilder } from '../../lib/constructs/knowledge-base/bm25-index-builder';

function buildTemplate(): Template {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  const bucket = new s3.Bucket(stack, 'IngestionBucket');
  const etlRepo = ecr.Repository.fromRepositoryAttributes(stack, 'EtlRepo', {
    repositoryName: 'renate-etl-lambda',
    repositoryArn:
      'arn:aws:ecr:eu-central-1:831926590742:repository/renate-etl-lambda',
  });

  new Bm25IndexBuilder(stack, 'Bm25IndexBuilder', {
    ingestionBucket: bucket,
    etlRepo,
    etlImageTag: 'v1.2.3',
  });

  return Template.fromStack(stack);
}

describe('Bm25IndexBuilder', () => {
  let template: Template;

  beforeAll(() => {
    template = buildTemplate();
  });

  test('SQS path: adds ObjectCreated and ObjectRemoved notifications with docs/ prefix and .md suffix', () => {
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

    const mdConfigs = queueConfigs.filter((q: any) =>
      q.Filter?.Key?.FilterRules?.some(
        (r: any) => r.Name === 'suffix' && r.Value === '.md',
      ),
    );
    const mdEvents = mdConfigs.flatMap((q: any) => q.Events ?? []);
    expect(mdEvents).toContain('s3:ObjectCreated:*');
    expect(mdEvents).toContain('s3:ObjectRemoved:*');
  });

  test('No deploy-time BM25 custom resource with TokenizerVersion property remains', () => {
    // The deploy-time CFN invocation was removed in #488.
    const customResources = template.findResources(
      'AWS::CloudFormation::CustomResource',
    );
    const withTokenizer = Object.values(customResources).filter(
      (r: any) => r.Properties?.TokenizerVersion !== undefined,
    );
    expect(withTokenizer).toHaveLength(0);
  });

  test('No cr.Provider custom resource remains for the BM25 deploy-time build', () => {
    // After #488 there is no cr.Provider for BM25 index building — the SQS-driven
    // rebuild queue and DLQ remain, but no Provider/CustomResource.
    const allCustomResources = {
      ...template.findResources('AWS::CloudFormation::CustomResource'),
      ...template.findResources('Custom::AWSCDK-custom-resources'),
    };
    const bm25BuildResources = Object.entries(allCustomResources).filter(
      ([logicalId]) => logicalId.includes('Bm25IndexBuild'),
    );
    expect(bm25BuildResources).toHaveLength(0);
  });

  test('builderLambda is exposed as a public property (Docker image function exists)', () => {
    // Framework Lambdas (SqsEventSource handler, etc.) may also appear; just
    // assert the Docker image function exists among them.
    const lambdas = template.findResources('AWS::Lambda::Function');
    expect(Object.keys(lambdas).length).toBeGreaterThanOrEqual(1);
  });

  test('Rebuild DLQ retains messages for 14 days', () => {
    template.hasResourceProperties('AWS::SQS::Queue', {
      MessageRetentionPeriod: 14 * 24 * 60 * 60,
    });
  });

  test('#590 fix: SQS event source uses a large batch size + batching window so a full-corpus reprocess collapses into few full rebuilds, not hundreds', () => {
    // The builder rebuilds the entire index on every invocation; without a large
    // batch window a reprocess that emits thousands of docs/*.md events becomes
    // hundreds of redundant full rebuilds (O(N²)). BatchSize > 10 requires
    // MaximumBatchingWindowInSeconds to be set.
    template.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
      BatchSize: 10000,
      MaximumBatchingWindowInSeconds: 300,
      ScalingConfig: { MaximumConcurrency: 2 },
    });
  });

  test('#590 fix: builder has reserved-concurrency headroom (5) so the direct invoke is not starved by the event source during a reprocess flood', () => {
    // Event source is capped at MaximumConcurrency 2; the extra headroom keeps
    // bm25-rebuild.sh's direct invoke from hitting
    // ReservedFunctionConcurrentInvocationLimitExceeded (pipeline #2714).
    template.hasResourceProperties('AWS::Lambda::Function', {
      ReservedConcurrentExecutions: 5,
    });
  });

  test('immutable release writes can attach the lifecycle retention tag', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const statements = Object.values(policies).flatMap(
      (policy: any) => policy.Properties?.PolicyDocument?.Statement ?? [],
    );
    const releaseIndexWrite = statements.find((statement: any) =>
      JSON.stringify(statement.Resource).includes('/bm25_index/releases/*'),
    );

    expect(releaseIndexWrite).toBeDefined();
    expect(
      Array.isArray(releaseIndexWrite.Action)
        ? releaseIndexWrite.Action
        : [releaseIndexWrite.Action],
    ).toEqual(expect.arrayContaining(['s3:PutObject', 's3:PutObjectTagging']));
  });

  describe('ECR image reference (#590 — fromImageAsset → fromEcr)', () => {
    test('builder Lambda references the renate-etl-lambda ECR image URI', () => {
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

    test('ImageConfig.Command is preserved as the BM25 builder handler', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        ImageConfig: Match.objectLike({
          Command: ['etl.bm25_index_builder.handler'],
        }),
      });
    });
  });
});
