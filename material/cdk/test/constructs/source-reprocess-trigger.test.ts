import { App, Stack } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as s3 from 'aws-cdk-lib/aws-s3';

import { SourceReprocessTrigger } from '../../lib/constructs/knowledge-base/source-reprocess-trigger';

function buildStack() {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  const bucket = new s3.Bucket(stack, 'SourceBucket');
  return { app, stack, bucket };
}

describe('SourceReprocessTrigger', () => {
  describe('static source entry', () => {
    test('creates a custom resource with static Sources entry', () => {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [
          {
            type: 'static',
            prefix: 'IN/faq/',
            suffixes: ['.html'],
          },
        ],
        reprocessVersion: 'test-version',
        runtimeIdentity: 'v1.2.3',
      });

      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::CloudFormation::CustomResource', {
        BucketName: { Ref: Match.stringLikeRegexp('SourceBucket') },
        Sources: [
          {
            Type: 'static',
            Prefix: 'IN/faq/',
            Suffixes: ['.html'],
          },
        ],
        ReprocessVersion: 'test-version',
        RuntimeIdentity: 'v1.2.3',
      });
    });

    test('custom resource waits for the updated reprocess handler', () => {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [
          {
            type: 'static',
            prefix: 'IN/faq/',
            suffixes: ['.html'],
          },
        ],
        reprocessVersion: 'test-version',
        runtimeIdentity: 'v1.2.3',
      });

      const resources = Template.fromStack(stack).findResources(
        'AWS::CloudFormation::CustomResource',
      );
      const reprocess = Object.values(resources).find((resource: any) =>
        (resource.Properties?.Sources ?? []).some(
          (source: any) => source.Type === 'static',
        ),
      ) as any;

      expect(reprocess.DependsOn).toEqual(
        expect.arrayContaining([expect.stringContaining('ReprocessFunction')]),
      );
    });

    test('static source: S3 IAM allows ListBucket with prefix condition', () => {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [{ type: 'static', prefix: 'IN/faq/', suffixes: ['.html'] }],
        reprocessVersion: 'v1',
      });

      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::Role', {
        Policies: Match.arrayWith([
          Match.objectLike({
            PolicyDocument: {
              Statement: Match.arrayWith([
                Match.objectLike({
                  Action: 's3:ListBucket',
                  Effect: 'Allow',
                }),
              ]),
            },
          }),
        ]),
      });
    });

    test('static source: no SSM policy is synthesized', () => {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [{ type: 'static', prefix: 'IN/faq/', suffixes: ['.html'] }],
        reprocessVersion: 'v1',
      });

      const template = Template.fromStack(stack);
      const roles = template.findResources('AWS::IAM::Role');

      const hasSsmPolicy = Object.values(roles).some((r: any) =>
        (r.Properties?.Policies ?? []).some((p: any) =>
          JSON.stringify(p).includes('ssm:GetParameter'),
        ),
      );
      expect(hasSsmPolicy).toBe(false);
    });

    test('disabled mode retains resources but removes source permissions', () => {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [{ type: 'static', prefix: 'IN/faq/', suffixes: ['.html'] }],
        reprocessVersion: 'v1',
        enabled: false,
      });

      const template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        Environment: {
          Variables: {
            SOURCE_REPROCESS_ENABLED: 'false',
          },
        },
      });
      template.hasResourceProperties('AWS::CloudFormation::CustomResource', {
        Enabled: false,
      });
      const roles = template.findResources('AWS::IAM::Role');
      expect(JSON.stringify(roles)).not.toContain('s3:PutObject');
      expect(JSON.stringify(roles)).not.toContain('ssm:GetParameter');
    });
  });

  describe('active-version source entry', () => {
    function buildWithActiveVersion() {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [
          {
            type: 'active-version',
            versionParameterName: '/dev/renate/data-artifact-version',
            releaseBasePrefix: 'releases/',
            suffixes: ['.xml', '.pdf'],
          },
        ],
        reprocessVersion: 'etl-hash-abc',
      });

      return Template.fromStack(stack);
    }

    test('creates custom resource with active-version Sources entry', () => {
      const template = buildWithActiveVersion();

      const allCr = template.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      const reprocessCrs = Object.values(allCr).filter((r: any) => {
        const sources: any[] = r.Properties?.Sources ?? [];
        return sources.some((s: any) => s.Type === 'active-version');
      });
      expect(reprocessCrs.length).toBeGreaterThan(0);
    });

    test('active-version entry serializes VersionParameterName, ReleaseBasePrefix, and Suffixes', () => {
      const template = buildWithActiveVersion();

      const allCr = template.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      let activeEntry: any;
      for (const r of Object.values(allCr) as any[]) {
        const found = (r.Properties?.Sources ?? []).find(
          (s: any) => s.Type === 'active-version',
        );
        if (found) {
          activeEntry = found;
          break;
        }
      }

      expect(activeEntry).toBeDefined();
      expect(activeEntry.VersionParameterName).toBe(
        '/dev/renate/data-artifact-version',
      );
      expect(activeEntry.ReleaseBasePrefix).toBe('releases/');
      expect(activeEntry.Suffixes).toEqual(
        expect.arrayContaining(['.xml', '.pdf']),
      );
    });

    test('active-version source: SSM GetParameter policy is synthesized', () => {
      const template = buildWithActiveVersion();

      template.hasResourceProperties('AWS::IAM::Role', {
        Policies: Match.arrayWith([
          Match.objectLike({
            PolicyDocument: {
              Statement: Match.arrayWith([
                Match.objectLike({
                  Action: 'ssm:GetParameter',
                  Effect: 'Allow',
                }),
              ]),
            },
          }),
        ]),
      });
    });

    test('does not synthesize an SSM value template parameter', () => {
      const template = buildWithActiveVersion().toJSON();
      const ssmValueParameters = Object.values(
        template.Parameters ?? {},
      ).filter(
        (parameter: any) =>
          parameter.Type === 'AWS::SSM::Parameter::Value<String>' &&
          parameter.Default === '/dev/renate/data-artifact-version',
      );

      expect(ssmValueParameters).toHaveLength(0);
    });

    test('active-version source: S3 releases/* resources are in the IAM policy', () => {
      const template = buildWithActiveVersion();

      const roles = template.findResources('AWS::IAM::Role');
      const hasReleasesResource = Object.values(roles).some((r: any) =>
        JSON.stringify(r.Properties?.Policies ?? []).includes('releases/*'),
      );
      expect(hasReleasesResource).toBe(true);
    });
  });

  describe('active FAQ source entry', () => {
    function buildWithActiveFaq() {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [
          {
            type: 'active-faq',
            versionParameterName: '/dev/renate/faq-artifact-version',
            releaseBasePrefix: 'releases/faq/',
            subPrefix: 'html/',
            suffixes: ['.html'],
          },
        ],
        reprocessVersion: 'faq-hash',
      });
      return Template.fromStack(stack);
    }

    test('serializes the exact active FAQ runtime contract', () => {
      const template = buildWithActiveFaq();
      const resources = template.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      const entry = Object.values(resources)
        .flatMap((resource: any) => resource.Properties?.Sources ?? [])
        .find((source: any) => source.Type === 'active-faq');

      expect(entry).toEqual({
        Type: 'active-faq',
        VersionParameterName: '/dev/renate/faq-artifact-version',
        ReleaseBasePrefix: 'releases/faq/',
        SubPrefix: 'html/',
        Suffixes: ['.html'],
      });
    });

    test('does not require the FAQ pointer at CloudFormation deploy time', () => {
      const parameters = buildWithActiveFaq().toJSON().Parameters ?? {};

      expect(Object.values(parameters)).not.toContainEqual({
        Type: 'AWS::SSM::Parameter::Value<String>',
        Default: '/dev/renate/faq-artifact-version',
      });
    });

    test('IAM reads only the FAQ pointer and scopes S3 to releases/faq', () => {
      const template = buildWithActiveFaq();
      const policies = JSON.stringify(
        Object.values(template.findResources('AWS::IAM::Role')).map(
          (role: any) => role.Properties?.Policies ?? [],
        ),
      );

      expect(policies).toContain(':parameter/dev/renate/faq-artifact-version');
      expect(policies).toContain('releases/faq/*');
      expect(policies).not.toMatch(/\/releases\/\*/);
    });

    test('requires an active FAQ sub-prefix', () => {
      const { stack, bucket } = buildStack();
      expect(
        () =>
          new SourceReprocessTrigger(stack, 'Trigger', {
            sourceBucket: bucket,
            sources: [
              {
                type: 'active-faq',
                versionParameterName: '/dev/renate/faq-artifact-version',
                releaseBasePrefix: 'releases/faq/',
                subPrefix: '',
                suffixes: ['.html'],
              } as any,
            ],
            reprocessVersion: 'faq-hash',
          }),
      ).toThrow(/active-faq source\[0\] requires/);
    });
  });

  describe('mixed sources (active-version + static)', () => {
    function buildMixed() {
      const { stack, bucket } = buildStack();

      new SourceReprocessTrigger(stack, 'Trigger', {
        sourceBucket: bucket,
        sources: [
          {
            type: 'active-version',
            versionParameterName: '/dev/renate/data-artifact-version',
            releaseBasePrefix: 'releases/',
            suffixes: ['.xml', '.pdf'],
          },
          {
            type: 'static',
            prefix: 'IN/faq/',
            suffixes: ['.html'],
          },
        ],
        reprocessVersion: 'mixed-hash',
      });

      return Template.fromStack(stack);
    }

    test('creates exactly one custom resource (no duplicate construct/provider)', () => {
      const template = buildMixed();
      const allCr = template.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      // Only one reprocess CR (may coexist with other CRs from CDK)
      const reprocessCrs = Object.values(allCr).filter((r: any) => {
        const sources: any[] = r.Properties?.Sources ?? [];
        return sources.length > 0;
      });
      expect(reprocessCrs).toHaveLength(1);
    });

    test('Sources contains both active-version and static entries', () => {
      const template = buildMixed();
      const allCr = template.findResources(
        'AWS::CloudFormation::CustomResource',
      );

      let sources: any[] = [];
      for (const r of Object.values(allCr) as any[]) {
        if ((r.Properties?.Sources ?? []).length > 0) {
          sources = r.Properties.Sources;
          break;
        }
      }

      const types = sources.map((s: any) => s.Type);
      expect(types).toContain('active-version');
      expect(types).toContain('static');
    });

    test('SSM GetParameter policy is synthesized (active-version entry)', () => {
      const template = buildMixed();
      template.hasResourceProperties('AWS::IAM::Role', {
        Policies: Match.arrayWith([
          Match.objectLike({
            PolicyDocument: {
              Statement: Match.arrayWith([
                Match.objectLike({
                  Action: 'ssm:GetParameter',
                  Effect: 'Allow',
                }),
              ]),
            },
          }),
        ]),
      });
    });
  });

  describe('validation', () => {
    test('throws if sources list is empty (TypeScript prevents this, guard still correct)', () => {
      const { stack, bucket } = buildStack();

      // TypeScript typing (non-empty tuple) prevents this at compile time,
      // but we test the runtime guard for the edge case.
      expect(() => {
        new SourceReprocessTrigger(stack, 'Trigger', {
          sourceBucket: bucket,
          sources: [] as any,
          reprocessVersion: 'v1',
        });
      }).toThrow(/sources must be non-empty/);
    });

    test('throws on an unknown source type', () => {
      const { stack, bucket } = buildStack();
      expect(() => {
        new SourceReprocessTrigger(stack, 'Trigger', {
          sourceBucket: bucket,
          sources: [{ type: 'bogus', prefix: 'x/', suffixes: ['.xml'] } as any],
          reprocessVersion: 'v1',
        });
      }).toThrow(/invalid type/);
    });

    test('throws on a static entry missing suffixes', () => {
      const { stack, bucket } = buildStack();
      expect(() => {
        new SourceReprocessTrigger(stack, 'Trigger', {
          sourceBucket: bucket,
          sources: [{ type: 'static', prefix: 'IN/faq/', suffixes: [] } as any],
          reprocessVersion: 'v1',
        });
      }).toThrow(/static source\[0\] requires/);
    });

    test('throws on an active-version entry missing releaseBasePrefix', () => {
      const { stack, bucket } = buildStack();
      expect(() => {
        new SourceReprocessTrigger(stack, 'Trigger', {
          sourceBucket: bucket,
          sources: [
            {
              type: 'active-version',
              versionParameterName: '/dev/renate/data-artifact-version',
              releaseBasePrefix: '',
              suffixes: ['.xml'],
            } as any,
          ],
          reprocessVersion: 'v1',
        });
      }).toThrow(/active-version source\[0\] requires/);
    });
  });
});
