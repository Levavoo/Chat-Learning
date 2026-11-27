import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import {
  AwsCustomResource,
  AwsCustomResourcePolicy,
} from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';

import {
  CustomResourceConfig,
  CustomResourceOperation,
} from '../interfaces/common';

export class CustomResourceFactory {
  static create(
    scope: Construct,
    id: string,
    config: CustomResourceConfig,
    createOperation: CustomResourceOperation,
    deleteOperation: CustomResourceOperation,
    updateOperation?: CustomResourceOperation,
  ): AwsCustomResource {
    const policy = AwsCustomResourcePolicy.fromStatements(
      config.policyStatements,
    );

    const resourceProps: any = {
      installLatestAwsSdk: true,
      policy,
      timeout: cdk.Duration.minutes(config.timeoutMinutes ?? 10),
      onCreate: {
        service: createOperation.service,
        action: createOperation.action,
        parameters: createOperation.parameters,
        outputPaths: createOperation.outputPaths,
        ignoreErrorCodeMatches:
          createOperation.ignoreErrorCodeMatches ?? config.ignoreErrorCodes,
      },
      onDelete: {
        service: deleteOperation.service,
        action: deleteOperation.action,
        parameters: deleteOperation.parameters,
        outputPaths: deleteOperation.outputPaths,
        ignoreErrorCodeMatches:
          deleteOperation.ignoreErrorCodeMatches ?? config.ignoreErrorCodes,
      },
    };

    if (updateOperation) {
      resourceProps.onUpdate = {
        service: updateOperation.service,
        action: updateOperation.action,
        parameters: updateOperation.parameters,
        outputPaths: updateOperation.outputPaths,
        ignoreErrorCodeMatches:
          updateOperation.ignoreErrorCodeMatches ?? config.ignoreErrorCodes,
      };
    }

    const customResource = new AwsCustomResource(scope, id, resourceProps);

    return customResource;
  }

  static createBedrockPolicyStatements(
    knowledgeBaseArn?: string,
    serviceRoleArn?: string,
  ): iam.PolicyStatement[] {
    const statements: iam.PolicyStatement[] = [];

    const kbResources = knowledgeBaseArn ? [knowledgeBaseArn] : ['*'];
    statements.push(
      new iam.PolicyStatement({
        sid: 'BedrockKnowledgeBaseOperations',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:CreateKnowledgeBase',
          'bedrock:GetKnowledgeBase',
          'bedrock:UpdateKnowledgeBase',
          'bedrock:DeleteKnowledgeBase',
          'bedrock:TagResource',
          'bedrock:ListTagsForResource',
        ],
        resources: kbResources,
      }),
    );

    // List operations require wildcard (AWS limitation)
    statements.push(
      new iam.PolicyStatement({
        sid: 'BedrockListOperations',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:ListKnowledgeBases'],
        resources: ['*'],
      }),
    );

    const roleResources = serviceRoleArn ? [serviceRoleArn] : ['*'];
    statements.push(
      new iam.PolicyStatement({
        sid: 'BedrockServiceRolePassRole',
        effect: iam.Effect.ALLOW,
        actions: ['iam:PassRole'],
        resources: roleResources,
        conditions: {
          StringEquals: {
            'iam:PassedToService': 'bedrock.amazonaws.com',
          },
        },
      }),
    );

    return statements;
  }

  static createS3VectorsPolicyStatements(
    vectorBucketArn?: string,
    vectorIndexArn?: string,
  ): iam.PolicyStatement[] {
    const statements: iam.PolicyStatement[] = [];

    const bucketResources = vectorBucketArn ? [vectorBucketArn] : ['*'];
    statements.push(
      new iam.PolicyStatement({
        sid: 'S3VectorsControlPlane',
        effect: iam.Effect.ALLOW,
        actions: [
          's3vectors:CreateVectorBucket',
          's3vectors:GetVectorBucket',
          's3vectors:UpdateVectorBucket',
          's3vectors:DeleteVectorBucket',
        ],
        resources: bucketResources,
      }),
    );

    const indexResources = vectorIndexArn ? [vectorIndexArn] : ['*'];
    statements.push(
      new iam.PolicyStatement({
        sid: 'S3VectorsIndexControlPlane',
        effect: iam.Effect.ALLOW,
        actions: [
          's3vectors:CreateIndex',
          's3vectors:GetIndex',
          's3vectors:UpdateIndex',
          's3vectors:DeleteIndex',
        ],
        resources: indexResources,
      }),
    );

    // List operations typically require wildcard (AWS service limitation)
    statements.push(
      new iam.PolicyStatement({
        sid: 'S3VectorsListOperations',
        effect: iam.Effect.ALLOW,
        actions: ['s3vectors:ListVectorBuckets', 's3vectors:ListIndexes'],
        resources: ['*'],
      }),
    );

    return statements;
  }
}
