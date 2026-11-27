import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

import { EmbeddingConfig } from '../interfaces/common';

export interface KnowledgeBaseRoleProps {
  readonly roleName: string;
  readonly description?: string;
  readonly ingestionBucket: s3.IBucket;
  readonly embeddingConfig: EmbeddingConfig;
  readonly vectorBucketArn?: string;
  readonly vectorIndexArn?: string;
  readonly knowledgeBaseArn?: string;
}

export class IamFactory {
  static createKnowledgeBaseRole(
    scope: Construct,
    id: string,
    props: KnowledgeBaseRoleProps,
  ): iam.IRole {
    const role = new iam.Role(scope, id, {
      roleName: props.roleName,
      description:
        props.description ??
        'Role for Bedrock Knowledge Base with S3 Vectors storage',
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      inlinePolicies: {
        S3IngestionPolicy: IamFactory.createS3IngestionPolicy(
          props.ingestionBucket,
        ),
        BedrockModelPolicy: IamFactory.createBedrockModelPolicy(
          props.embeddingConfig,
        ),
        S3VectorsPolicy: IamFactory.createS3VectorsDataPlanePolicy(
          props.vectorIndexArn,
        ),
      },
    });

    return role;
  }

  private static createS3IngestionPolicy(
    bucket: s3.IBucket,
  ): iam.PolicyDocument {
    return new iam.PolicyDocument({
      statements: [
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
          resources: [`${bucket.bucketArn}/*`],
        }),
      ],
    });
  }

  private static createBedrockModelPolicy(
    embeddingConfig: EmbeddingConfig,
  ): iam.PolicyDocument {
    return new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          sid: 'BedrockModelAccess',
          effect: iam.Effect.ALLOW,
          actions: ['bedrock:InvokeModel'],
          resources: [embeddingConfig.modelArn],
        }),
      ],
    });
  }

  private static createS3VectorsDataPlanePolicy(
    vectorIndexArn?: string,
  ): iam.PolicyDocument {
    // S3 Vectors may require wildcard permissions for some operations
    const resources = vectorIndexArn ? [vectorIndexArn] : ['*'];

    return new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          sid: 'S3VectorsDataPlane',
          effect: iam.Effect.ALLOW,
          actions: [
            's3vectors:PutVectors',
            's3vectors:GetVectors',
            's3vectors:ListVectors',
            's3vectors:QueryVectors',
            's3vectors:DeleteVectors',
          ],
          resources,
          ...(vectorIndexArn && {
            conditions: {
              StringEquals: {
                's3vectors:index-arn': vectorIndexArn,
              },
            },
          }),
        }),
      ],
    });
  }

  static createCleanupLambdaRole(
    scope: Construct,
    id: string,
    roleName: string,
    knowledgeBaseArns?: string[],
  ): iam.IRole {
    const role = new iam.Role(scope, id, {
      roleName,
      description: 'Role for Bedrock Knowledge Base cleanup Lambda function',
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      inlinePolicies: {
        LambdaBasicExecution: IamFactory.createLambdaBasicExecutionPolicy(),
        BedrockCleanupPolicy:
          IamFactory.createBedrockCleanupPolicy(knowledgeBaseArns),
      },
    });

    return role;
  }

  private static createLambdaBasicExecutionPolicy(): iam.PolicyDocument {
    return new iam.PolicyDocument({
      statements: [
        new iam.PolicyStatement({
          sid: 'CloudWatchLogsAccess',
          effect: iam.Effect.ALLOW,
          actions: [
            'logs:CreateLogGroup',
            'logs:CreateLogStream',
            'logs:PutLogEvents',
          ],
          resources: ['*'],
        }),
      ],
    });
  }

  private static createBedrockCleanupPolicy(
    knowledgeBaseArns?: string[],
  ): iam.PolicyDocument {
    const statements: iam.PolicyStatement[] = [];

    const kbResources =
      knowledgeBaseArns && knowledgeBaseArns.length > 0
        ? knowledgeBaseArns
        : ['*'];

    statements.push(
      new iam.PolicyStatement({
        sid: 'BedrockKnowledgeBaseOperations',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:GetKnowledgeBase', 'bedrock:DeleteKnowledgeBase'],
        resources: kbResources,
      }),
    );

    if (knowledgeBaseArns && knowledgeBaseArns.length > 0) {
      const dataSourceArns = knowledgeBaseArns.map(
        (kbArn) => `${kbArn}/data-sources/*`,
      );
      statements.push(
        new iam.PolicyStatement({
          sid: 'BedrockDataSourceOperations',
          effect: iam.Effect.ALLOW,
          actions: ['bedrock:GetDataSource', 'bedrock:DeleteDataSource'],
          resources: dataSourceArns,
        }),
      );

      const ingestionJobArns = knowledgeBaseArns.map(
        (kbArn) => `${kbArn}/data-sources/*/ingestion-jobs/*`,
      );
      statements.push(
        new iam.PolicyStatement({
          sid: 'BedrockIngestionJobOperations',
          effect: iam.Effect.ALLOW,
          actions: ['bedrock:GetIngestionJob'],
          resources: ingestionJobArns,
        }),
      );
    }

    // List operations typically require wildcard resources
    statements.push(
      new iam.PolicyStatement({
        sid: 'BedrockListOperations',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:ListDataSources',
          'bedrock:ListIngestionJobs',
          'bedrock:ListKnowledgeBases',
        ],
        resources: ['*'],
      }),
    );

    return new iam.PolicyDocument({ statements });
  }

  static addS3BucketPermissions(
    role: iam.Role,
    bucket: s3.IBucket,
    actions: string[] = ['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
  ): void {
    role.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions,
        resources: [`${bucket.bucketArn}/*`],
      }),
    );

    role.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['s3:ListBucket'],
        resources: [bucket.bucketArn],
      }),
    );
  }

  static createMinimalRole(
    scope: Construct,
    id: string,
    props: {
      roleName: string;
      description: string;
      assumedBy: iam.IPrincipal;
      policyStatements: iam.PolicyStatement[];
      managedPolicies?: iam.IManagedPolicy[];
    },
  ): iam.IRole {
    const policyDocument = new iam.PolicyDocument({
      statements: props.policyStatements,
    });

    const roleProps: any = {
      roleName: props.roleName,
      description: props.description,
      assumedBy: props.assumedBy,
      inlinePolicies: {
        MinimalPolicy: policyDocument,
      },
    };

    if (props.managedPolicies) {
      roleProps.managedPolicies = props.managedPolicies;
    }

    return new iam.Role(scope, id, roleProps);
  }
}
