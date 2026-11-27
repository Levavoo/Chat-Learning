import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface IamRoleProps {
  readonly roleName: string;
  readonly assumedBy: iam.IPrincipal;
  readonly description?: string;
  readonly policies?: iam.PolicyStatement[];
}

export class IamFactory {
  static createRole(
    scope: Construct,
    id: string,
    props: IamRoleProps,
  ): iam.Role {
    const role = new iam.Role(scope, id, {
      roleName: props.roleName,
      assumedBy: props.assumedBy,
      description: props.description,
    });

    if (props.policies) {
      props.policies.forEach((policy) => {
        role.addToPolicy(policy);
      });
    }

    return role;
  }

  static createLambdaExecutionRole(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
    additionalPolicies?: iam.PolicyStatement[],
  ): iam.Role {
    const basePolicies: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [
          `arn:aws:logs:*:*:log-group:/aws/lambda/${prefix}-*-${envName}:*`,
        ],
      }),
    ];

    if (additionalPolicies) {
      basePolicies.push(...additionalPolicies);
    }

    return this.createRole(scope, id, {
      roleName: `${prefix}-lambda-exec-${envName}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: `Lambda execution role for ${prefix} in ${envName}`,
      policies: basePolicies,
    });
  }

  static createBedrockKnowledgeBaseRole(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
    embeddingModelArn: string,
    vectorBucketArn: string,
    ingestionBucketArn: string,
  ): iam.Role {
    const policies: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:InvokeModel', 'bedrock:GetFoundationModel'],
        resources: [embeddingModelArn],
      }),
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['s3:GetObject', 's3:ListBucket'],
        resources: [ingestionBucketArn, `${ingestionBucketArn}/*`],
      }),
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [`arn:aws:logs:*:*:log-group:/aws/bedrock/knowledgebases/*`],
      }),
    ];

    return this.createRole(scope, id, {
      roleName: `${prefix}-kb-role-${envName}`,
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: `Bedrock Knowledge Base role for ${prefix} in ${envName}`,
      policies,
    });
  }

  static createEtlLambdaRole(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
    sourceBucketArn: string,
    outputBucketArn: string,
  ): iam.Role {
    const policies: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject'],
        resources: [
          sourceBucketArn,
          `${sourceBucketArn}/*`,
          outputBucketArn,
          `${outputBucketArn}/*`,
        ],
      }),
    ];

    return this.createLambdaExecutionRole(scope, id, prefix, envName, policies);
  }
}
