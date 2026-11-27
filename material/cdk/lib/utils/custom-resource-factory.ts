import { CustomResource, Duration, RemovalPolicy } from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';

export interface CustomResourceProps {
  readonly serviceToken: string;
  readonly resourceType: string;
  readonly properties: { [key: string]: any };
  readonly removalPolicy?: RemovalPolicy;
}

export class CustomResourceFactory {
  static createCustomResource(
    scope: Construct,
    id: string,
    props: CustomResourceProps,
  ): CustomResource {
    return new CustomResource(scope, id, {
      serviceToken: props.serviceToken,
      resourceType: props.resourceType,
      properties: props.properties,
      removalPolicy: props.removalPolicy || RemovalPolicy.RETAIN,
    });
  }

  static createLambdaProvider(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
    handlerFile: string,
    handler: string,
    environment: { [key: string]: string },
    additionalPolicies?: iam.PolicyStatement[],
  ): lambda.Function {
    const roleName = `${prefix}-${id.toLowerCase()}-provider-${envName}`;

    const role = new iam.Role(scope, `${id}ProviderRole`, {
      roleName,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: `Custom resource provider for ${id}`,
    });

    role.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [`arn:aws:logs:*:*:log-group:/aws/lambda/${roleName}:*`],
      }),
    );

    if (additionalPolicies) {
      additionalPolicies.forEach((policy) => {
        role.addToPolicy(policy);
      });
    }

    return new lambda.Function(scope, `${id}Provider`, {
      functionName: roleName,
      runtime: lambda.Runtime.PYTHON_3_13,
      handler,
      code: lambda.Code.fromAsset(
        path.join(__dirname, `../custom-resources/${handlerFile}/`),
      ),
      timeout: Duration.minutes(15),
      role,
      environment,
    });
  }

  static createKbSyncProvider(
    scope: Construct,
    id: string,
    prefix: string,
    envName: string,
    knowledgeBaseId: string,
    dataSourceId: string,
    ingestionBucket: string,
  ): lambda.Function {
    const environment = {
      KNOWLEDGE_BASE_ID: knowledgeBaseId,
      DATA_SOURCE_ID: dataSourceId,
      INGESTION_BUCKET: ingestionBucket,
      SYNC_PREFIX: 'docs/',
    };

    const additionalPolicies: iam.PolicyStatement[] = [
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:StartIngestionJob',
          'bedrock:GetIngestionJob',
          'bedrock:ListIngestionJobs',
        ],
        resources: [
          `arn:aws:bedrock:*:*:knowledge-base/${knowledgeBaseId}`,
          `arn:aws:bedrock:*:*:knowledge-base/${knowledgeBaseId}/data-source/${dataSourceId}`,
        ],
      }),
    ];

    return this.createLambdaProvider(
      scope,
      id,
      prefix,
      envName,
      'kb-sync-trigger',
      'kb-sync-handler.handler',
      environment,
      additionalPolicies,
    );
  }
}
