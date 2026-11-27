import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

import { DeletionBehavior } from '../interfaces/common';
import { deterministicName } from '../constants/resource-names';

// =============================================================================
// Types
// =============================================================================

export interface BucketProps {
  /** Purpose identifier used for naming */
  readonly purpose: string;
  /** Deployment environment */
  readonly environment: string;
  /**
   * Optional environment segment used only in the physical name.
   *
   * Existing resources omit this to preserve the legacy `environment`
   * context/default naming contract. New resources may opt into the correct
   * environment without renaming legacy buckets.
   */
  readonly physicalNameEnvironment?: string;
  /** Enable versioning. */
  readonly versioned?: boolean;
  /** Deletion behavior on stack destroy. */
  readonly deletionBehavior?: DeletionBehavior;
  /** KMS key ARN for encryption. Default: S3-managed encryption */
  readonly kmsKeyArn?: string;
  /** Block all public access. Default: true */
  readonly blockPublicAccess?: boolean;
  /** Enforce SSL/TLS connections. Default: true */
  readonly enforceSSL?: boolean;
  /** S3 lifecycle rules owned by the bucket's creating stack. */
  readonly lifecycleRules?: s3.LifecycleRule[];
}

/** Resolved bucket configuration after merging defaults and overrides */
interface ResolvedConfig {
  readonly bucketName: string;
  readonly versioned: boolean;
  readonly removalPolicy: cdk.RemovalPolicy;
  readonly autoDeleteObjects: boolean;
  readonly encryption: s3.BucketEncryption;
  readonly encryptionKey?: cdk.aws_kms.IKey;
  readonly blockPublicAccess?: s3.BlockPublicAccess;
  readonly enforceSSL: boolean;
  readonly objectOwnership: s3.ObjectOwnership;
  readonly lifecycleRules: s3.LifecycleRule[];
}

/** Environment-specific default overrides */
interface EnvironmentDefaults {
  readonly versioned: boolean;
  readonly deletionBehavior: DeletionBehavior;
}

/** S3 bucket factory with environment-aware defaults */
export class S3Factory {
  // ===========================================================================
  // Environment Defaults
  // ===========================================================================

  private static readonly DEFAULTS: Record<string, EnvironmentDefaults> = {
    dev: {
      versioned: false,
      deletionBehavior: DeletionBehavior.DELETE,
    },
    staging: {
      versioned: true,
      deletionBehavior: DeletionBehavior.DELETE,
    },
    prod: {
      versioned: true,
      deletionBehavior: DeletionBehavior.RETAIN,
    },
  };

  static createBucket(
    scope: Construct,
    id: string,
    props: BucketProps,
  ): s3.Bucket {
    const config = S3Factory.resolveConfig(scope, props);
    const bucket = S3Factory.createBucketResource(scope, id, config);

    if (config.enforceSSL) {
      S3Factory.applySSLPolicy(bucket);
    }

    return bucket;
  }

  /** Priority: provided props > environment defaults > fallbacks */
  private static resolveConfig(
    scope: Construct,
    props: BucketProps,
  ): ResolvedConfig {
    const stack = cdk.Stack.of(scope);
    const envDefaults = S3Factory.DEFAULTS[props.environment] ?? {
      versioned: false,
      deletionBehavior: DeletionBehavior.RETAIN,
    };

    const versioned = props.versioned ?? envDefaults.versioned;
    const deletionBehavior =
      props.deletionBehavior ?? envDefaults.deletionBehavior;
    const blockPublicAccess = props.blockPublicAccess ?? true;
    const enforceSSL = props.enforceSSL ?? true;

    const removalPolicy = S3Factory.toRemovalPolicy(deletionBehavior);

    const config: ResolvedConfig = {
      bucketName: deterministicName(
        stack,
        s3.CfnBucket.CFN_RESOURCE_TYPE_NAME,
        props.purpose.toLowerCase(),
        props.physicalNameEnvironment,
      ),
      versioned,
      removalPolicy,
      autoDeleteObjects: removalPolicy === cdk.RemovalPolicy.DESTROY,
      encryption: props.kmsKeyArn
        ? s3.BucketEncryption.KMS
        : s3.BucketEncryption.S3_MANAGED,
      enforceSSL,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: props.lifecycleRules ?? [],
      ...(blockPublicAccess && {
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      }),
    };

    if (props.kmsKeyArn) {
      return {
        ...config,
        encryptionKey: cdk.aws_kms.Key.fromKeyArn(
          scope,
          `${props.purpose}-Key`,
          props.kmsKeyArn,
        ),
      };
    }

    return config;
  }

  private static createBucketResource(
    scope: Construct,
    id: string,
    config: ResolvedConfig,
  ): s3.Bucket {
    return new s3.Bucket(scope, id, {
      bucketName: config.bucketName,
      versioned: config.versioned,
      removalPolicy: config.removalPolicy,
      autoDeleteObjects: config.autoDeleteObjects,
      encryption: config.encryption,
      enforceSSL: config.enforceSSL,
      objectOwnership: config.objectOwnership,
      lifecycleRules: config.lifecycleRules,
      ...(config.blockPublicAccess && {
        blockPublicAccess: config.blockPublicAccess,
      }),
      ...(config.encryptionKey && { encryptionKey: config.encryptionKey }),
    });
  }

  private static applySSLPolicy(bucket: s3.Bucket): void {
    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'DenyInsecureConnections',
        effect: iam.Effect.DENY,
        principals: [new iam.AnyPrincipal()],
        actions: ['s3:*'],
        resources: [bucket.bucketArn, `${bucket.bucketArn}/*`],
        conditions: {
          Bool: { 'aws:SecureTransport': 'false' },
        },
      }),
    );
  }

  // ===========================================================================
  // Utilities
  // ===========================================================================

  private static toRemovalPolicy(
    behavior: DeletionBehavior,
  ): cdk.RemovalPolicy {
    switch (behavior) {
      case DeletionBehavior.DELETE:
        return cdk.RemovalPolicy.DESTROY;
      case DeletionBehavior.SNAPSHOT:
        return cdk.RemovalPolicy.SNAPSHOT;
      case DeletionBehavior.RETAIN:
      default:
        return cdk.RemovalPolicy.RETAIN;
    }
  }
}
