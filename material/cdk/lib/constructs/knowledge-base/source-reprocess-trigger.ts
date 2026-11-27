import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as nodejs from 'aws-cdk-lib/aws-lambda-nodejs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cr from 'aws-cdk-lib/custom-resources';
import { Construct, IDependable } from 'constructs';
import * as path from 'path';

import { deterministicName } from '../../constants/resource-names';

/**
 * A static source entry — the prefix is known at deploy time (e.g. IN/faq/).
 */
export interface StaticReprocessSource {
  readonly type: 'static';
  /** S3 prefix to list and re-emit */
  readonly prefix: string;
  /** File suffixes to include (e.g. ['.html']) */
  readonly suffixes: string[];
}

/**
 * An active-version source entry — the exact prefix is resolved at runtime via
 * an SSM parameter written by the build-data-artifacts CI job.
 *
 * The parameter value is expected to be a semver string like `v1.5.0`.
 * The Lambda constructs the full prefix as `{releaseBasePrefix}{value}/`.
 */
export interface ActiveVersionReprocessSource {
  readonly type: 'active-version';
  /** Runtime-only SSM parameter name containing the active data version. */
  readonly versionParameterName: string;
  /** Base prefix for releases, e.g. 'releases/' */
  readonly releaseBasePrefix: string;
  /** File suffixes to include (e.g. ['.xml', '.pdf']) */
  readonly suffixes: string[];
}

export type ReprocessSource =
  | StaticReprocessSource
  | ActiveVersionReprocessSource
  | ActiveFaqReprocessSource;

/**
 * An active-FAQ source entry — the exact prefix is resolved at runtime via
 * an SSM parameter written by the faq-publish CI job.
 *
 * The parameter value is expected to be `sha256-<hex64>`.
 * The Lambda constructs the full prefix as `{releaseBasePrefix}{value}/{subPrefix}`.
 */
export interface ActiveFaqReprocessSource {
  readonly type: 'active-faq';
  /** Runtime-only SSM parameter name containing the active FAQ coordinate. */
  readonly versionParameterName: string;
  /** Base prefix for FAQ releases, e.g. 'releases/faq/' */
  readonly releaseBasePrefix: string;
  /** Sub-prefix appended after the version value, e.g. 'html/' */
  readonly subPrefix: string;
  /** File suffixes to include (e.g. ['.html']) */
  readonly suffixes: string[];
}

export interface SourceReprocessTriggerProps {
  /** Source bucket whose objects should be re-emitted into the ETL S3 event flow */
  readonly sourceBucket: s3.IBucket;
  /**
   * Non-empty list of source entries to reprocess.
   * Each entry is either a static prefix or an active-version SSM lookup.
   */
  readonly sources: [ReprocessSource, ...ReprocessSource[]];
  /** Changing value that forces the custom resource to reprocess source files */
  readonly reprocessVersion: string;
  /**
   * Immutable identity of the ETL runtime image. Updates that only change the
   * source fingerprint are skipped while this identity remains unchanged.
   */
  readonly runtimeIdentity?: string;
  /** Optional dependency to ensure pipelines are live before reprocessing */
  readonly dependsOn?: IDependable;
  /**
   * Disable all source access and replay behavior while retaining the
   * construct's existing CloudFormation resources and physical IDs.
   * @default true
   */
  readonly enabled?: boolean;
}

/** Re-emits ETL source objects by copying them in place to trigger S3 ObjectCreated events. */
export class SourceReprocessTrigger extends Construct {
  public readonly reprocessLambda: nodejs.NodejsFunction;
  public readonly resource: cdk.CustomResource;

  constructor(
    scope: Construct,
    id: string,
    props: SourceReprocessTriggerProps,
  ) {
    super(scope, id);

    if (props.sources.length === 0) {
      throw new Error('SourceReprocessTrigger: sources must be non-empty');
    }

    // The TS discriminated union enforces one mode per entry at compile time,
    // but a runtime guard protects against untyped call sites and malformed
    // serialization.
    props.sources.forEach((src, i) => {
      if (src.type === 'static') {
        if (!src.prefix || !src.suffixes || src.suffixes.length === 0) {
          throw new Error(
            `SourceReprocessTrigger: static source[${i}] requires a non-empty prefix and suffixes`,
          );
        }
      } else if (src.type === 'active-version') {
        if (
          !src.versionParameterName ||
          !src.releaseBasePrefix ||
          !src.suffixes ||
          src.suffixes.length === 0
        ) {
          throw new Error(
            `SourceReprocessTrigger: active-version source[${i}] requires versionParameter, releaseBasePrefix, and non-empty suffixes`,
          );
        }
      } else if (src.type === 'active-faq') {
        if (
          !src.versionParameterName ||
          !src.releaseBasePrefix ||
          !src.subPrefix ||
          !src.suffixes ||
          src.suffixes.length === 0
        ) {
          throw new Error(
            `SourceReprocessTrigger: active-faq source[${i}] requires versionParameterName, releaseBasePrefix, subPrefix, and non-empty suffixes`,
          );
        }
      } else {
        throw new Error(
          `SourceReprocessTrigger: source[${i}] has invalid type "${(src as { type?: string }).type}" — expected "static", "active-version", or "active-faq"`,
        );
      }
    });

    const stack = cdk.Stack.of(this);
    const enabled = props.enabled !== false;

    const staticPrefixes = props.sources
      .filter((s): s is StaticReprocessSource => s.type === 'static')
      .map((s) => s.prefix);

    const activeVersionSources = props.sources.filter(
      (s): s is ActiveVersionReprocessSource => s.type === 'active-version',
    );

    const activeFaqSources = props.sources.filter(
      (s): s is ActiveFaqReprocessSource => s.type === 'active-faq',
    );

    // Keep both CI-owned pointers runtime-only. Importing a not-yet-created SSM
    // parameter through CDK emits an AWS::SSM::Parameter::Value template
    // parameter, which CloudFormation resolves before the first deployment.
    const allSsmParameterArns = [
      ...activeVersionSources.map((s) =>
        stack.formatArn({
          service: 'ssm',
          resource: 'parameter',
          resourceName: s.versionParameterName.replace(/^\//, ''),
        }),
      ),
      ...activeFaqSources.map((s) =>
        stack.formatArn({
          service: 'ssm',
          resource: 'parameter',
          resourceName: s.versionParameterName.replace(/^\//, ''),
        }),
      ),
    ];

    const dynamicBasePrefixes = [
      ...activeVersionSources.map((source) => source.releaseBasePrefix),
      ...activeFaqSources.map((source) => source.releaseBasePrefix),
    ];

    // Scope each dynamic source to its configured release base. A FAQ-only
    // trigger therefore receives releases/faq/* rather than all releases/*.
    const listPrefixConditions: string[] = [
      ...staticPrefixes.flatMap((p) => [p, `${p}*`]),
      ...dynamicBasePrefixes.flatMap((prefix) => [prefix, `${prefix}*`]),
    ];

    const objectArns: string[] = [
      ...staticPrefixes.map((p) => `${props.sourceBucket.bucketArn}/${p}*`),
      ...dynamicBasePrefixes.map(
        (prefix) => `${props.sourceBucket.bucketArn}/${prefix}*`,
      ),
    ];

    const role = new iam.Role(this, 'ReprocessRole', {
      roleName: deterministicName(
        stack,
        iam.CfnRole.CFN_RESOURCE_TYPE_NAME,
        'etl-source-reprocess-role',
      ),
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for ETL source reprocess custom resource',
      inlinePolicies: {
        LambdaBasicExecution: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              effect: iam.Effect.ALLOW,
              actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
              ],
              resources: [
                `arn:aws:logs:${stack.region}:${stack.account}:log-group:/aws/lambda/*`,
              ],
            }),
          ],
        }),
        ...(enabled
          ? {
              S3ReprocessAccess: new iam.PolicyDocument({
                statements: [
                  new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: ['s3:ListBucket'],
                    resources: [props.sourceBucket.bucketArn],
                    conditions: {
                      StringLike: {
                        's3:prefix': listPrefixConditions,
                      },
                    },
                  }),
                  new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: [
                      's3:GetObject',
                      's3:GetObjectTagging',
                      's3:PutObject',
                      's3:PutObjectTagging',
                    ],
                    resources: objectArns,
                  }),
                ],
              }),
              ...(allSsmParameterArns.length > 0
                ? {
                    SsmReadAccess: new iam.PolicyDocument({
                      statements: allSsmParameterArns.map(
                        (parameterArn) =>
                          new iam.PolicyStatement({
                            effect: iam.Effect.ALLOW,
                            actions: ['ssm:GetParameter'],
                            resources: [parameterArn],
                          }),
                      ),
                    }),
                  }
                : {}),
            }
          : {}),
      },
    });

    const functionName = deterministicName(
      stack,
      lambda.CfnFunction.CFN_RESOURCE_TYPE_NAME,
      'etl-source-reprocess',
    );

    this.reprocessLambda = new nodejs.NodejsFunction(
      this,
      'ReprocessFunction',
      {
        functionName,
        entry: path.join(
          __dirname,
          '../../custom-resources/source-reprocess/source-reprocess-handler.ts',
        ),
        handler: 'handler',
        runtime: lambda.Runtime.NODEJS_20_X,
        role,
        timeout: cdk.Duration.minutes(15),
        memorySize: 256,
        environment: {
          SOURCE_REPROCESS_ENABLED: enabled ? 'true' : 'false',
        },
        bundling: {
          minify: true,
          sourceMap: false,
          externalModules: ['@aws-sdk/*'],
        },
        logGroup: new logs.LogGroup(this, 'ReprocessFunctionLogGroup', {
          logGroupName: `/aws/lambda/${functionName}`,
          retention: logs.RetentionDays.ONE_WEEK,
          removalPolicy: cdk.RemovalPolicy.DESTROY,
        }),
      },
    );

    const provider = new cr.Provider(this, 'Provider', {
      onEventHandler: this.reprocessLambda,
    });

    // Serialize sources into the custom resource properties so the handler
    // can resolve each one at runtime without any synth-time SSM lookups.
    const serializedSources = props.sources.map((src) => {
      if (src.type === 'static') {
        return {
          Type: 'static',
          Prefix: src.prefix,
          Suffixes: src.suffixes,
        };
      } else if (src.type === 'active-version') {
        return {
          Type: 'active-version',
          VersionParameterName: src.versionParameterName,
          ReleaseBasePrefix: src.releaseBasePrefix,
          Suffixes: src.suffixes,
        };
      } else {
        return {
          Type: 'active-faq',
          VersionParameterName: src.versionParameterName,
          ReleaseBasePrefix: src.releaseBasePrefix,
          SubPrefix: src.subPrefix,
          Suffixes: src.suffixes,
        };
      }
    });

    this.resource = new cdk.CustomResource(this, 'Resource', {
      serviceToken: provider.serviceToken,
      properties: {
        BucketName: props.sourceBucket.bucketName,
        Sources: serializedSources,
        ReprocessVersion: props.reprocessVersion,
        Enabled: enabled,
        ...(props.runtimeIdentity && {
          RuntimeIdentity: props.runtimeIdentity,
        }),
      },
    });

    // The custom resource must execute the newly deployed handler during an
    // update; otherwise a property change could race the Lambda code update
    // and run the previous replay behavior.
    this.resource.node.addDependency(this.reprocessLambda);

    if (props.dependsOn) {
      this.resource.node.addDependency(props.dependsOn);
    }
  }
}
