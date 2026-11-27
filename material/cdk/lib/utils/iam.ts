import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';

export function createS3BucketPolicy(
  bucket: s3.IBucket,
  prefixes: string[],
): iam.PolicyStatement[] {
  const s3ObjectResources = prefixes.flatMap((prefix) => [
    bucket.arnForObjects(`${prefix}*`),
  ]);

  return [
    new iam.PolicyStatement({
      sid: 'S3ListBucket',
      effect: iam.Effect.ALLOW,
      actions: ['s3:ListBucket', 's3:ListBucketVersions'],
      resources: [bucket.bucketArn],
    }),
    new iam.PolicyStatement({
      sid: 'S3GetObject',
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetObject', 's3:GetObjectVersion'],
      resources: s3ObjectResources,
    }),
  ];
}

export function createBedrockInvokePolicy(
  modelArns: string[],
): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'BedrockModelAccess',
    effect: iam.Effect.ALLOW,
    actions: ['bedrock:InvokeModel'],
    resources: modelArns,
  });
}

export function createS3VectorsDataPlanePolicy(
  indexArn?: string,
): iam.PolicyStatement {
  const s3VectorsDataPlaneActions = [
    's3vectors:PutVectors',
    's3vectors:GetVectors',
    's3vectors:ListVectors',
    's3vectors:QueryVectors',
    's3vectors:DeleteVectors',
  ];
  // TODO: We might need to scope this down
  const resources = indexArn ? [indexArn] : ['*'];

  return new iam.PolicyStatement({
    sid: 'S3VectorsDataPlane',
    effect: iam.Effect.ALLOW,
    actions: s3VectorsDataPlaneActions,
    resources,
  });
}

export function createS3VectorsControlPlanePolicy(): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'S3VectorsControlPlane',
    effect: iam.Effect.ALLOW,
    actions: [
      's3vectors:CreateVectorBucket',
      's3vectors:GetVectorBucket',
      's3vectors:DeleteVectorBucket',
      's3vectors:CreateIndex',
      's3vectors:GetIndex',
      's3vectors:DeleteIndex',
      's3vectors:ListIndexes',
    ],
    // TODO: also this might need to get scoped down
    resources: ['*'],
  });
}

export function createCloudWatchLogsPolicy(
  region: string,
  account: string,
): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'CloudWatchLogs',
    effect: iam.Effect.ALLOW,
    actions: [
      'logs:CreateLogGroup',
      'logs:CreateLogStream',
      'logs:PutLogEvents',
      'logs:DescribeLogGroups',
      'logs:DescribeLogStreams',
    ],
    resources: [
      `arn:aws:logs:${region}:${account}:log-group:/aws/bedrock/*`,
      `arn:aws:logs:${region}:${account}:log-group:/aws/bedrock/*:*`,
    ],
  });
}

export function createBedrockKnowledgeBasePolicy(): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'BedrockKnowledgeBaseManagement',
    effect: iam.Effect.ALLOW,
    actions: [
      'bedrock:CreateKnowledgeBase',
      'bedrock:GetKnowledgeBase',
      'bedrock:DeleteKnowledgeBase',
      'bedrock:UpdateKnowledgeBase',
    ],
    // TODO: scope this down for prod
    resources: ['*'],
  });
}

export function createBedrockCleanupPolicy(): iam.PolicyStatement {
  return new iam.PolicyStatement({
    sid: 'BedrockCleanupPermissions',
    effect: iam.Effect.ALLOW,
    actions: [
      'bedrock:ListDataSources',
      'bedrock:GetDataSource',
      'bedrock:DeleteDataSource',
      'bedrock:ListIngestionJobs',
      'bedrock:GetIngestionJob',
      'bedrock:GetKnowledgeBase',
      'bedrock:DeleteKnowledgeBase',
    ],
    resources: ['*'],
  });
}
