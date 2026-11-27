import { Construct } from 'constructs';
import {
  ArnFormat,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  Tags,
} from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ssm from 'aws-cdk-lib/aws-ssm';

import { isProdEnv } from '../config/chatbot-config';

/** Lambda execution role with VPC + CloudWatch Logs permissions. */
function createLambdaRole(
  scope: Construct,
  id: string,
  functionName: string,
  region: string,
  account: string,
): iam.Role {
  const role = new iam.Role(scope, id, {
    assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
    description: `Execution role for ${functionName}`,
  });

  // Equivalent to AWSLambdaVPCAccessExecutionRole.
  role.addToPolicy(
    new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ec2:CreateNetworkInterface',
        'ec2:DescribeNetworkInterfaces',
        'ec2:DeleteNetworkInterface',
        'ec2:AssignPrivateIpAddresses',
        'ec2:UnassignPrivateIpAddresses',
      ],
      resources: ['*'],
    }),
  );

  // Review envs (TKT-REV-*) clone this role onto "<base>-chat-review-<slug>";
  // the review log group must be writable or the review Lambda runs blind.
  const reviewLogGroupName = functionName.replace(/-[^-]+$/, '-review-*');
  role.addToPolicy(
    new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
      ],
      resources: [
        `arn:aws:logs:${region}:${account}:log-group:/aws/lambda/${functionName}:*`,
        `arn:aws:logs:${region}:${account}:log-group:/aws/lambda/${reviewLogGroupName}:*`,
      ],
    }),
  );

  return role;
}

export interface LambdaBackendProps {
  readonly prefix: string;
  readonly vpc: ec2.IVpc;
  readonly securityGroup: ec2.ISecurityGroup;
  readonly privateSubnets: ec2.ISubnet[];
  readonly envName: string;
  /** Always the dev account. */
  readonly ecrAccount: string;
  readonly allowedOrigin?: string;
  /** Seconds. @default 30 */
  readonly timeout?: number;
  /** MB. @default 512 */
  readonly memorySize?: number;
  /** @default 'INFO' */
  readonly logLevel?: string;
  /** @default true */
  readonly enableTracing?: boolean;
  /** @default RetentionDays.ONE_WEEK */
  readonly logRetentionDays?: logs.RetentionDays;
  /** @default 'https://mock.example.com' */
  readonly mockBotEndpoint?: string;
  /** @default lambda.Architecture.X86_64 */
  readonly architecture?: lambda.Architecture;
  readonly knowledgeBaseId?: string;
  readonly bedrockModelId?: string;
  readonly guardrailId?: string;
  /** @default "DRAFT" when guardrailId is set */
  readonly guardrailVersion?: string;
  /** @default "eu.amazon.nova-lite-v1:0" */
  readonly guardrailAgentModelId?: string;
  /** Required for cross-region guardrails (e.g. "eu.guardrail.v1:0"). */
  readonly guardrailProfileIdentifier?: string;
  /** @default `${prefix}-conversations-${envName}` */
  readonly conversationTableName?: string;
  /** @default 30 */
  readonly conversationTtlDays?: number;
  readonly bm25IndexBucket?: string;
  /** Atomic retrieval selector name — the parameter may be absent during foundation. */
  readonly retrievalManifestParameterName?: string;
  /** Additional KB IDs a validated manifest may select. */
  readonly retrievalKnowledgeBaseIds?: string[];
  /** Additional processed buckets a validated manifest may select. */
  readonly retrievalBm25Buckets?: string[];
  /** @default false */
  readonly hydeEnabled?: boolean;
  /** @default bedrockModelId */
  readonly hydeModelId?: string;
  /** "rag" | "agent". @default "rag" */
  readonly searchMode?: string;
  /** Empty means load from local bundled data. */
  readonly agentSearchIndexBucket?: string;
  /** When set, chat Lambda can self-flip reserved concurrency and update the KVS key. */
  readonly maintenanceModeStoreArn?: string;
  readonly langfuseHost?: string;
  readonly langfuseSecretName?: string;
  /**
   * Last LangFuse key rotation (UTC, YYYY-MM-DDTHH:MMZ). The chat handler
   * reads the secret once per cold start (observability.py), so bumping this
   * value is the reviewed way to force fresh execution environments after a
   * rotation. Requires langfuseHost and langfuseSecretName.
   */
  readonly langfuseKeyRotatedAt?: string;
  readonly otelIncludeContent?: boolean;
}

const PROD_LANGFUSE_HOST = 'https://langfuse.renate-observability.de';

// #773 time-boxed exception: Prod shares the Dev LangFuse until the dedicated
// Prod instance (#745/#749/#751) is live. Remove with #773.
const TRANSITIONAL_SHARED_LANGFUSE_HOST =
  'https://langfuse-renate-dev.kilab-platform.de';

/** Enforce endpoint + content isolation even before Prod LangFuse activates. */
function validateLangfuseEndpointIsolation(
  props: Pick<
    LambdaBackendProps,
    'envName' | 'langfuseHost' | 'langfuseSecretName' | 'otelIncludeContent'
  >,
): void {
  const referencesProdEndpoint = props.langfuseHost === PROD_LANGFUSE_HOST;
  const referencesTransitionalSharedEndpoint =
    props.langfuseHost === TRANSITIONAL_SHARED_LANGFUSE_HOST;

  if (props.envName === 'prod') {
    const hasProdLangfuseConfiguration =
      Boolean(props.langfuseHost) || Boolean(props.langfuseSecretName);

    // Absence is intentional until the separate activation work package #751.
    if (!hasProdLangfuseConfiguration) {
      if (props.otelIncludeContent) {
        throw new Error(
          'Prod LangFuse content export cannot be enabled while LangFuse is inactive.',
        );
      }
      return;
    }

    const usesApprovedEndpoint =
      props.langfuseHost === PROD_LANGFUSE_HOST ||
      referencesTransitionalSharedEndpoint;

    if (!usesApprovedEndpoint || !props.langfuseSecretName) {
      throw new Error(
        'Prod LangFuse must use its dedicated endpoint (or the #773 transitional shared endpoint) and a configured credential reference.',
      );
    }
    // #774: Content export (prompt/response bodies in traces) is explicitly
    // approved by default in every stage, including Prod, until this default
    // is deliberately withdrawn for Prod in a follow-up change.
    return;
  }

  if (referencesProdEndpoint) {
    throw new Error(
      'Only the prod deployment may reference the dedicated Prod LangFuse endpoint.',
    );
  }
}

export class LambdaBackend extends Construct {
  readonly chatHandler: lambda.Function;
  readonly healthHandler: lambda.Function;
  readonly analyticsHandler: lambda.Function;
  readonly chatRepository: ecr.IRepository;
  readonly chatLogGroup: logs.LogGroup;
  readonly consentLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: LambdaBackendProps) {
    super(scope, id);
    validateLangfuseEndpointIsolation(props);
    // Without host AND secret the backend never loads the key, so a marker
    // would be dropped silently and the rotation would look done.
    if (
      props.langfuseKeyRotatedAt &&
      (!props.langfuseHost || !props.langfuseSecretName)
    ) {
      throw new Error(
        'langfuseKeyRotatedAt requires langfuseHost and langfuseSecretName — otherwise no function reads the key and the marker has no effect.',
      );
    }

    const region = Stack.of(this).region;
    const account = Stack.of(this).account;
    const timeout = props.timeout || 28;
    const memorySize = props.memorySize || 512;
    const logLevel = props.logLevel || 'INFO';
    const enableTracing = props.enableTracing !== false;
    const logRetentionDays =
      props.logRetentionDays || logs.RetentionDays.ONE_WEEK;
    const mockBotEndpoint = props.mockBotEndpoint || 'https://mock.example.com';
    const architecture = props.architecture || lambda.Architecture.X86_64;

    const commonEnvironment: Record<string, string> = {
      LOG_LEVEL: logLevel,
      REGION: region,
      ENVIRONMENT: props.envName,
      ALLOWED_ORIGIN: props.allowedOrigin || '*',
      DYNAMODB_TABLE_NAME:
        props.conversationTableName ||
        `${props.prefix}-conversations-${props.envName}`,
      CONVERSATION_TTL_DAYS: String(props.conversationTtlDays ?? 30),
    };

    if (props.knowledgeBaseId) {
      commonEnvironment.KNOWLEDGE_BASE_ID = props.knowledgeBaseId;
    }

    if (props.bedrockModelId) {
      commonEnvironment.BEDROCK_MODEL_ID = props.bedrockModelId;
    }

    if (props.guardrailId) {
      commonEnvironment.BEDROCK_GUARDRAIL_ID = props.guardrailId;
      commonEnvironment.BEDROCK_GUARDRAIL_VERSION =
        props.guardrailVersion || 'DRAFT';
    }

    if (props.guardrailAgentModelId) {
      commonEnvironment.GUARDRAIL_AGENT_MODEL_ID = props.guardrailAgentModelId;
    }

    if (props.hydeEnabled) {
      commonEnvironment.HYDE_ENABLED = 'true';
      if (props.hydeModelId) {
        commonEnvironment.HYDE_MODEL_ID = props.hydeModelId;
      }
    }

    if (props.bm25IndexBucket) {
      commonEnvironment.BM25_INDEX_BUCKET = props.bm25IndexBucket;
      commonEnvironment.BM25_ENABLED = 'true';
    }

    if (props.retrievalManifestParameterName) {
      commonEnvironment.RETRIEVAL_MANIFEST_PARAMETER =
        props.retrievalManifestParameterName;
    }

    if (props.searchMode) {
      commonEnvironment.SEARCH_MODE = props.searchMode;
    }
    if (props.agentSearchIndexBucket) {
      commonEnvironment.AGENT_SEARCH_INDEX_BUCKET =
        props.agentSearchIndexBucket;
    }

    if (props.langfuseHost) {
      commonEnvironment.LANGFUSE_HOST = props.langfuseHost;
      if (props.langfuseSecretName) {
        commonEnvironment.LANGFUSE_SECRET_NAME = props.langfuseSecretName;
      }
      commonEnvironment.OTEL_INCLUDE_CONTENT = props.otelIncludeContent
        ? 'true'
        : 'false';
    }

    // ECR repo owned by terraform/bootstrap/dev/ecr_chatbot.tf; explicit ARN
    // so cross-account deploys hit the correct dev-account prefix.
    const repoName = `${props.prefix}-chat-lambda`;
    this.chatRepository = ecr.Repository.fromRepositoryAttributes(
      this,
      'ChatRepository',
      {
        repositoryName: repoName,
        repositoryArn: Stack.of(this).formatArn({
          service: 'ecr',
          resource: 'repository',
          resourceName: repoName,
          account: props.ecrAccount,
        }),
      },
    );

    // QA retrieval promotion pins the image at synth so code rolls back
    // atomically with the retrieval selector; everyone else uses SSM.
    const chatbotImageTagContext = this.node.tryGetContext(
      'chatbotImageTag',
    ) as string | undefined;
    if (
      chatbotImageTagContext &&
      !/^(v?\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?|sha256:[0-9a-f]{64})$/.test(
        chatbotImageTagContext,
      )
    ) {
      throw new Error(
        `Invalid chatbotImageTag context value "${chatbotImageTagContext}" — ` +
          'use an immutable semantic version or sha256 digest.',
      );
    }
    const imageTag =
      chatbotImageTagContext ??
      ssm.StringParameter.valueForTypedStringParameterV2(
        this,
        `/${props.envName}/renate/image-tag`,
      );

    const chatFunctionName = `${props.prefix}-chat-${props.envName}`;
    const chatLogGroup = new logs.LogGroup(this, 'ChatLogGroup', {
      logGroupName: `/aws/lambda/${chatFunctionName}`,
      retention: logRetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    // Dedicated consent log group — DSFA audit trail, separate from app logs.
    const consentLogGroupName = `/renate/${props.envName}/consent-log`;
    const consentLogGroup = new logs.LogGroup(this, 'ConsentLogGroup', {
      logGroupName: consentLogGroupName,
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: isProdEnv(props.envName)
        ? RemovalPolicy.RETAIN
        : RemovalPolicy.DESTROY,
    });

    const chatRole = createLambdaRole(
      this,
      'ChatHandlerRole',
      chatFunctionName,
      region,
      account,
    );

    const chatHandler = new lambda.DockerImageFunction(this, 'ChatHandler', {
      functionName: chatFunctionName,
      description:
        'Backend orchestrator for chatbot API - handles chat requests',
      code: lambda.DockerImageCode.fromEcr(this.chatRepository, {
        tagOrDigest: imageTag,
      }),
      timeout: Duration.seconds(timeout),
      memorySize: memorySize,
      architecture: architecture,

      vpc: props.vpc,
      vpcSubnets: {
        subnets: props.privateSubnets,
      },
      securityGroups: [props.securityGroup],

      environment: {
        ...commonEnvironment,
        BOT_ENDPOINT_MOCK: mockBotEndpoint,
        CONSENT_LOG_GROUP: consentLogGroupName,
        // Only the chat handler loads the LangFuse key (observability.py via
        // orchestrator.py); health.py does not, so it gets no restart marker.
        ...(props.langfuseKeyRotatedAt
          ? { LANGFUSE_KEY_ROTATED_AT: props.langfuseKeyRotatedAt }
          : {}),
      },

      tracing: enableTracing ? lambda.Tracing.ACTIVE : lambda.Tracing.DISABLED,
      logGroup: chatLogGroup,
      role: chatRole,
    });

    const chatFunctionArn = Stack.of(this).formatArn({
      service: 'lambda',
      resource: 'function',
      resourceName: chatFunctionName,
      arnFormat: ArnFormat.COLON_RESOURCE_NAME,
    });

    const healthFunctionName = `${props.prefix}-health-${props.envName}`;
    const healthLogGroup = new logs.LogGroup(this, 'HealthLogGroup', {
      logGroupName: `/aws/lambda/${healthFunctionName}`,
      retention: logRetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const healthRole = createLambdaRole(
      this,
      'HealthHandlerRole',
      healthFunctionName,
      region,
      account,
    );

    const healthHandler = new lambda.DockerImageFunction(
      this,
      'HealthHandler',
      {
        functionName: healthFunctionName,
        description: 'Health check endpoint for chatbot backend',
        code: lambda.DockerImageCode.fromEcr(this.chatRepository, {
          tagOrDigest: imageTag,
          cmd: ['backend_orchestrator.health.lambda_handler'],
        }),
        timeout: Duration.seconds(10),
        memorySize: 256,
        architecture: architecture,
        vpc: props.vpc,
        vpcSubnets: {
          subnets: props.privateSubnets,
        },
        securityGroups: [props.securityGroup],
        environment: commonEnvironment,
        tracing: enableTracing
          ? lambda.Tracing.ACTIVE
          : lambda.Tracing.DISABLED,
        logGroup: healthLogGroup,
        role: healthRole,
      },
    );

    healthRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'HealthCheckDynamoDB',
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:GetItem'],
        resources: [
          `arn:aws:dynamodb:${region}:${account}:table/${props.prefix}-conversations-${props.envName}`,
        ],
      }),
    );
    healthRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'HealthCheckBedrock',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:GetFoundationModel'],
        resources: ['*'],
      }),
    );
    healthRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'HealthCheckKnowledgeBase',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:GetKnowledgeBase'],
        resources: [`arn:aws:bedrock:${region}:${account}:knowledge-base/*`],
      }),
    );

    // RFC-0009 analytics Lambda: same image, different handler, read-only DDB.
    // Isolated failure domain from chat.
    const analyticsFunctionName = `${props.prefix}-analytics-${props.envName}`;
    const analyticsLogGroup = new logs.LogGroup(this, 'AnalyticsLogGroup', {
      logGroupName: `/aws/lambda/${analyticsFunctionName}`,
      retention: logRetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const analyticsRole = createLambdaRole(
      this,
      'AnalyticsHandlerRole',
      analyticsFunctionName,
      region,
      account,
    );

    const analyticsHandler = new lambda.DockerImageFunction(
      this,
      'AnalyticsHandler',
      {
        functionName: analyticsFunctionName,
        description:
          'Analytics endpoint for editorial dashboard — read-only DynamoDB',
        code: lambda.DockerImageCode.fromEcr(this.chatRepository, {
          tagOrDigest: imageTag,
          cmd: ['backend_orchestrator.analytics_handler.handler'],
        }),
        timeout: Duration.seconds(29),
        memorySize: 256,
        architecture: architecture,
        vpc: props.vpc,
        vpcSubnets: {
          subnets: props.privateSubnets,
        },
        securityGroups: [props.securityGroup],
        environment: {
          LOG_LEVEL: logLevel,
          REGION: region,
          ENVIRONMENT: props.envName,
          ALLOWED_ORIGIN: props.allowedOrigin || '*',
          DYNAMODB_TABLE_NAME:
            props.conversationTableName ||
            `${props.prefix}-conversations-${props.envName}`,
          ...(props.agentSearchIndexBucket
            ? { AGENT_SEARCH_INDEX_BUCKET: props.agentSearchIndexBucket }
            : {}),
        },
        tracing: enableTracing
          ? lambda.Tracing.ACTIVE
          : lambda.Tracing.DISABLED,
        logGroup: analyticsLogGroup,
        role: analyticsRole,
      },
    );

    if (props.envName) {
      Tags.of(analyticsHandler).add('Environment', props.envName);
    }
    Tags.of(analyticsHandler).add('Project', 'DigiBro-Chatbot');
    Tags.of(analyticsHandler).add('Component', 'Analytics');

    chatRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
          'bedrock:Converse',
        ],
        // TODO: restrict resources
        resources: ['*'],
      }),
    );

    chatRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
        resources: [consentLogGroup.logGroupArn],
      }),
    );

    chatRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:Query',
          'dynamodb:GetItem',
          'dynamodb:DeleteItem',
          'dynamodb:BatchWriteItem',
        ],
        resources: [
          `arn:aws:dynamodb:${region}:${account}:table/${props.conversationTableName}`,
        ],
      }),
    );

    // Analytics is strictly read-only on table + GSI (RFC-0009).
    const conversationTableArn = `arn:aws:dynamodb:${region}:${account}:table/${
      props.conversationTableName ||
      `${props.prefix}-conversations-${props.envName}`
    }`;
    analyticsRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:Query', 'dynamodb:GetItem'],
        resources: [
          conversationTableArn,
          `${conversationTableArn}/index/domain-created_at-index`,
        ],
      }),
    );

    if (props.agentSearchIndexBucket) {
      analyticsRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['s3:GetObject'],
          resources: [
            `arn:aws:s3:::${props.agentSearchIndexBucket}/agent-search-index/index.json`,
          ],
        }),
      );
    }

    if (props.maintenanceModeStoreArn) {
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'lambda:PutFunctionConcurrency',
            'lambda:DeleteFunctionConcurrency',
          ],
          resources: [chatFunctionArn],
        }),
      );

      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['cloudfront-keyvaluestore:UpdateKeys'],
          resources: [props.maintenanceModeStoreArn],
        }),
      );
    }

    if (props.guardrailId) {
      const guardrailResources = [
        `arn:aws:bedrock:${region}:${account}:guardrail/${props.guardrailId}`,
      ];

      // Wildcard region: cross-region profiles can route to any region.
      if (props.guardrailProfileIdentifier) {
        guardrailResources.push(
          `arn:aws:bedrock:*:${account}:guardrail-profile/${props.guardrailProfileIdentifier}`,
        );
      }

      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['bedrock:ApplyGuardrail', 'bedrock:GetGuardrail'],
          resources: guardrailResources,
        }),
      );
    }

    // Permit both retrieval slots; runtime picks one validated manifest per request.
    const retrievalKnowledgeBaseIds = [
      props.knowledgeBaseId,
      ...(props.retrievalKnowledgeBaseIds ?? []),
    ].filter((id): id is string => Boolean(id));
    if (retrievalKnowledgeBaseIds.length > 0) {
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'bedrock:Retrieve',
            'bedrock:RetrieveAndGenerate',
            'bedrock:GetKnowledgeBase',
            'bedrock:ListKnowledgeBases',
          ],
          resources: retrievalKnowledgeBaseIds.map(
            (id) => `arn:aws:bedrock:${region}:${account}:knowledge-base/${id}`,
          ),
        }),
      );
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['bedrock:Rerank'],
          resources: ['*'],
        }),
      );
    }

    // Blue legacy objects + both slots' immutable BM25 releases. Embedded
    // release metadata removes the active path's dependency on mutable docs/.
    if (props.bm25IndexBucket || props.retrievalBm25Buckets?.length) {
      const legacyResources = props.bm25IndexBucket
        ? [
            `arn:aws:s3:::${props.bm25IndexBucket}/bm25_index/*`,
            `arn:aws:s3:::${props.bm25IndexBucket}/docs/*`,
          ]
        : [];
      const immutableReleaseResources = (props.retrievalBm25Buckets ?? []).map(
        (bucket) => `arn:aws:s3:::${bucket}/bm25_index/releases/*`,
      );
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['s3:GetObject'],
          resources: [...legacyResources, ...immutableReleaseResources],
        }),
      );
    }

    if (props.retrievalManifestParameterName) {
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['ssm:GetParameter'],
          resources: [
            `arn:${Stack.of(this).partition}:ssm:${region}:${account}:parameter${props.retrievalManifestParameterName}`,
          ],
        }),
      );
    }

    if (props.agentSearchIndexBucket) {
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['s3:GetObject', 's3:ListBucket'],
          resources: [
            `arn:aws:s3:::${props.agentSearchIndexBucket}`,
            `arn:aws:s3:::${props.agentSearchIndexBucket}/agent-search-index/*`,
          ],
        }),
      );
    }

    if (props.langfuseSecretName) {
      chatRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['secretsmanager:GetSecretValue'],
          resources: [
            `arn:aws:secretsmanager:${region}:${account}:secret:${props.langfuseSecretName}-*`,
          ],
        }),
      );
    }

    if (props.envName) {
      Tags.of(chatHandler).add('Environment', props.envName);
      Tags.of(healthHandler).add('Environment', props.envName);
    }
    Tags.of(chatHandler).add('Project', 'DigiBro-Chatbot');
    Tags.of(chatHandler).add('Component', 'Backend');
    Tags.of(healthHandler).add('Project', 'DigiBro-Chatbot');
    Tags.of(healthHandler).add('Component', 'HealthCheck');

    this.chatHandler = chatHandler;
    this.healthHandler = healthHandler;
    this.analyticsHandler = analyticsHandler;
    this.chatLogGroup = chatLogGroup;
    this.consentLogGroup = consentLogGroup;

    new CfnOutput(this, 'ChatHandlerArn', {
      value: chatHandler.functionArn,
      description: 'ARN of the chat handler Lambda function',
      exportName: `${props.envName || 'default'}-ChatHandlerArn`,
    });

    new CfnOutput(this, 'ChatHandlerName', {
      value: chatHandler.functionName,
      description: 'Name of the chat handler Lambda function',
      exportName: `${props.envName || 'default'}-ChatHandlerName`,
    });

    new CfnOutput(this, 'HealthHandlerArn', {
      value: healthHandler.functionArn,
      description: 'ARN of the health check Lambda function',
      exportName: `${props.envName || 'default'}-HealthHandlerArn`,
    });

    new CfnOutput(this, 'HealthHandlerName', {
      value: healthHandler.functionName,
      description: 'Name of the health check Lambda function',
      exportName: `${props.envName || 'default'}-HealthHandlerName`,
    });

    new CfnOutput(this, 'ChatHandlerLogGroup', {
      value: chatHandler.logGroup.logGroupName,
      description: 'CloudWatch Log Group for chat handler',
    });

    new CfnOutput(this, 'HealthHandlerLogGroup', {
      value: healthHandler.logGroup.logGroupName,
      description: 'CloudWatch Log Group for health handler',
    });

    new CfnOutput(this, 'ChatRepositoryUri', {
      value: this.chatRepository.repositoryUri,
      description: 'ECR Repository URI for Lambda container images',
    });

    new CfnOutput(this, 'LambdaBackendChatHandlerName', {
      value: chatHandler.functionName,
      description:
        'Name of the chat handler Lambda function (for maintenance-switch)',
    });
  }

  getChatRepository(): ecr.IRepository {
    return this.chatRepository;
  }

  getChatHandler(): lambda.Function {
    return this.chatHandler;
  }

  getHealthHandler(): lambda.Function {
    return this.healthHandler;
  }

  getAnalyticsHandler(): lambda.Function {
    return this.analyticsHandler;
  }

  grantInvoke(principal: iam.IPrincipal): void {
    this.chatHandler.grantInvoke(principal);
    this.healthHandler.grantInvoke(principal);
  }

  grantChatInvoke(principal: iam.IPrincipal): void {
    this.chatHandler.grantInvoke(principal);
  }

  grantHealthInvoke(principal: iam.IPrincipal): void {
    this.healthHandler.grantInvoke(principal);
  }
}
