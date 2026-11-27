import * as s3 from 'aws-cdk-lib/aws-s3';
import { RemovalPolicy, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface S3BucketProps {
  readonly bucketName: string;
  readonly removalPolicy?: RemovalPolicy;
  readonly versioned?: boolean;
  readonly encryption?: s3.BucketEncryption;
  readonly blockPublicAccess?: s3.BlockPublicAccess;
  readonly lifecycleRules?: s3.LifecycleRule[];
}

export class S3Factory {
  static createBucket(
    scope: Construct,
    id: string,
    props: S3BucketProps,
  ): s3.Bucket {
    return new s3.Bucket(scope, id, {
      bucketName: props.bucketName,
      removalPolicy: props.removalPolicy || RemovalPolicy.RETAIN,
      versioned: props.versioned || false,
      encryption: props.encryption || s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess:
        props.blockPublicAccess || s3.BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: props.lifecycleRules || [],
    });
  }

  static createSourceBucket(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
  ): s3.Bucket {
    const bucketName = `${prefix}-source-${envName}-${scope.node.addr}`;

    return this.createBucket(scope, id, {
      bucketName,
      removalPolicy: RemovalPolicy.DESTROY,
      versioned: true,
      lifecycleRules: [
        {
          id: 'DeleteOldObjects',
          enabled: envName === 'dev',
          expiration: Duration.days(7),
          abortIncompleteMultipartUploadAfter: Duration.days(1),
        },
      ],
    });
  }

  static createIngestionBucket(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
  ): s3.Bucket {
    const bucketName = `${prefix}-ingestion-${envName}-${scope.node.addr}`;

    return this.createBucket(scope, id, {
      bucketName,
      removalPolicy: RemovalPolicy.DESTROY,
      versioned: true,
      lifecycleRules: [
        {
          id: 'DeleteOldObjects',
          enabled: envName === 'dev',
          expiration: Duration.days(7),
          abortIncompleteMultipartUploadAfter: Duration.days(1),
        },
      ],
    });
  }

  static createVectorBucket(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
  ): s3.Bucket {
    const bucketName = `${prefix}-vectors-${envName}-${scope.node.addr}`;

    return this.createBucket(scope, id, {
      bucketName,
      removalPolicy: RemovalPolicy.DESTROY,
      versioned: false,
      encryption: s3.BucketEncryption.S3_MANAGED,
    });
  }
}
