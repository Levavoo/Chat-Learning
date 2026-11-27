import { Construct } from 'constructs';
import { Stack, Duration, CfnOutput, RemovalPolicy } from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Networking } from './constructs/networking';
import { ApiGatewayConstruct } from './constructs/api-gateway';
import { LambdaBackend } from './constructs/lambda-backend';
import { Auth } from './constructs/auth';
import { AngularFrontend } from './constructs/frontend';
import { BedrockGuardrail } from './constructs/bedrock-guardrail';
import { WafConstruct } from './constructs/waf';
import { DEFAULT_WAF_MANAGED_RULE_ACTIONS } from './config/waf-managed-rules';
import { identityProvider } from './utils/identity-provider';
import { AlertingTopic } from './constructs/monitoring/alerting-topic';
import { ChatbotAlarms } from './constructs/monitoring/chatbot-alarms';
import { MonitoringDashboard } from './constructs/monitoring/monitoring-dashboard';
import { BudgetAlerts } from './constructs/monitoring/budget-alerts';
import { BudgetPacing } from './constructs/monitoring/budget-pacing';
import { ConversationTable } from './constructs/dynamodb';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as lambda from 'aws-cdk-lib/aws-lambda';

import { ChatbotStackProps, isProdEnv } from './config/chatbot-config';
import {
  isManifestManagedEnvironment,
  retrievalMetricNamespace,
} from './config/retrieval-environment';

export class ChatbotStack extends Stack {
  public readonly networking: Networking;
  public readonly apiGateway: ApiGatewayConstruct;
  public readonly lambdaBackend: LambdaBackend;
  public readonly auth: Auth;
  public readonly frontend?: AngularFrontend;
  public readonly guardrail?: BedrockGuardrail;
  public readonly conversationTable: ConversationTable;
  constructor(scope: Construct, id: string, props: ChatbotStackProps) {
    super(scope, id, props);

    const isProd = isProdEnv(props.envName);
    const manifestManaged = isManifestManagedEnvironment(props.envName);
    const logLevel = props.backend?.logLevel || (isProd ? 'INFO' : 'DEBUG');
    const logRetentionDays =
      props.backend?.logRetentionDays ||
      (isProd ? logs.RetentionDays.ONE_MONTH : logs.RetentionDays.ONE_WEEK);

    const knowledgeBaseId =
      props.backend?.knowledgeBaseId ??
      ssm.StringParameter.valueForStringParameter(
        this,
        `/${props.envName}/renate/knowledge-base-id`,
      );

    const bm25IndexBucket = props.backend?.enableBm25
      ? (props.backend?.bm25IndexBucket ??
        ssm.StringParameter.valueForStringParameter(
          this,
          `/${props.envName}/renate/ingestion-bucket-name`,
        ))
      : undefined;

    // Manifest-managed envs resolve an atomic semantic+BM25 manifest at runtime;
    // CDK passes the selector name only — the promotion workflow owns the value.
    const retrievalManifestParameterName = manifestManaged
      ? `/${props.envName}/renate/retrieval/active-manifest`
      : undefined;
    const greenKnowledgeBaseId = manifestManaged
      ? ssm.StringParameter.valueForStringParameter(
          this,
          `/${props.envName}/renate/retrieval/slots/green/knowledge-base-id`,
        )
      : undefined;
    const greenProcessedBucket =
      manifestManaged && props.backend?.enableBm25
        ? ssm.StringParameter.valueForStringParameter(
            this,
            `/${props.envName}/renate/retrieval/slots/green/processed-bucket-name`,
          )
        : undefined;

    const agentSearchIndexBucket =
      props.backend?.searchMode === 'agent'
        ? (props.backend?.agentSearchIndexBucket ??
          ssm.StringParameter.valueForStringParameter(
            this,
            `/${props.envName}/renate/ingestion-bucket-name`,
          ))
        : props.backend?.agentSearchIndexBucket;

    this.networking = new Networking(this, 'Networking', {
      prefix: props.prefix,
      vpcCidr: props.network?.vpcCidr || '10.0.0.0/16',
      maxAzs: props.network?.maxAzs || 2,
      natGateways: props.network?.natGateways || 1,
      enableFlowLogs: true,
      envName: props.envName,
    });

    const accessLogBucket = new s3.Bucket(this, 'AccessLogsBucket', {
      // Prod suffixes account id; demo still owns the pre-#473 historic name.
      bucketName:
        props.envName === 'prod'
          ? `${props.prefix}-access-logs-${props.envName}-${Stack.of(this).region}-${Stack.of(this).account}`
          : `${props.prefix}-access-logs-${props.envName}-${Stack.of(this).region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
      lifecycleRules: [
        {
          expiration: Duration.days(90),
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: Duration.days(30),
            },
          ],
        },
      ],
    });

    this.frontend = new AngularFrontend(this, 'Frontend', {
      prefix: props.prefix,
      envName: props.envName,
      webAclId: props.frontend.webAclId,
      accessLogBucket: accessLogBucket,
      enableIpV6: props.frontend.enableIpV6 !== false,
      alternateDomainName: props.frontend.domainName,
      hostedZoneId: props.frontend.hostedZoneId,
      hostedZoneName: props.frontend.hostedZoneName,
      certificateArn: props.frontend.certificateArn,
      dnsRecordName: props.frontend.dnsRecordName,
      geoRestrictionCountries: props.frontend.geoRestrictionCountries,
    });

    const frontendOrigins = [
      this.frontend.getOrigin(),
      ...(props.frontend.origin ? [props.frontend.origin] : []),
    ];

    this.apiGateway = new ApiGatewayConstruct(this, 'ApiGateway', {
      prefix: props.prefix,
      vpc: this.networking.getVpc(),
      envName: props.envName,
      enableLogging: true,
      enableTracing: props.backend?.enableTracing !== false,
      allowedOrigins: frontendOrigins,
      throttleRateLimit: props.backend?.apiThrottleRateLimit || 10000,
      throttleBurstLimit: props.backend?.apiThrottleBurstLimit || 5000,
      chatThrottleRateLimit: props.backend?.chatThrottleRateLimit,
      chatThrottleBurstLimit: props.backend?.chatThrottleBurstLimit,
    });

    // /api/* and /health through CloudFront → API GW keeps same-origin for browser.
    this.frontend.addApiBehaviors(
      this.apiGateway.getApiDomain(),
      this.apiGateway.getStageName(),
    );

    this.auth = new Auth(this, 'Auth', {
      prefix: props.prefix,
      envName: props.envName,
      origin: this.frontend.getOrigin(),
      userPoolDomainPrefixKey: props.auth.userPoolDomainPrefix,
      idp: identityProvider([]),
      allowedSignUpEmailDomains: props.auth.allowedSignUpEmailDomains || [],
      selfSignUpEnabled: props.auth.selfSignUpEnabled !== false,
      tokenValidity: Duration.minutes(props.auth.tokenValidityMinutes || 60),
    });

    if (props.waf?.wafEnabled !== false) {
      new WafConstruct(this, 'Waf', {
        prefix: props.prefix,
        envName: props.envName,
        rateLimitPerIp: props.waf?.wafRateLimitPerIp || 500,
        botControlEnabled: props.waf?.wafBotControlEnabled !== false,
        managedRuleActions: (
          props.waf?.wafManagedRuleActions ?? DEFAULT_WAF_MANAGED_RULE_ACTIONS
        ).regional,
        ruleCountOverrides: props.waf?.wafRuleCountOverrides?.regional,
        apiGatewayStageArn: this.apiGateway.api.deploymentStage.stageArn,
      });
    }

    if (props.backend?.enableGuardrails !== false) {
      this.guardrail = new BedrockGuardrail(this, 'Guardrail', {
        prefix: props.prefix,
        envName: props.envName,
        blockedInputMessage: props.backend?.guardrailBlockedInputMessage,
        blockedOutputMessage: props.backend?.guardrailBlockedOutputMessage,
        promptAttackFilterStrength: 'MEDIUM',
        crossRegionConfig: {
          guardrailProfileIdentifier: 'eu.guardrail.v1:0',
        },
      });
    }

    this.conversationTable = new ConversationTable(this, 'ConversationTable', {
      prefix: props.prefix,
      envName: props.envName,
    });

    this.lambdaBackend = new LambdaBackend(this, 'LambdaBackend', {
      prefix: props.prefix,
      vpc: this.networking.getVpc(),
      securityGroup: this.networking.getLambdaSecurityGroup(),
      privateSubnets: this.networking.getPrivateSubnets(),
      envName: props.envName,
      timeout: props.backend?.lambdaTimeout || 28,
      memorySize: props.backend?.lambdaMemorySize || 512,
      logLevel: logLevel,
      enableTracing: props.backend?.enableTracing !== false,
      logRetentionDays: logRetentionDays,
      knowledgeBaseId: knowledgeBaseId,
      bedrockModelId: props.backend?.bedrockModelId,
      allowedOrigin: this.frontend.getOrigin(),
      guardrailId: this.guardrail?.getGuardrailId(),
      guardrailVersion: this.guardrail?.getGuardrailVersion(),
      guardrailAgentModelId:
        props.backend?.enableGuardrails !== false
          ? props.backend?.guardrailAgentModelId || 'eu.amazon.nova-lite-v1:0'
          : undefined,
      guardrailProfileIdentifier: 'eu.guardrail.v1:0',
      conversationTableName: this.conversationTable.tableName,
      conversationTtlDays: props.backend?.conversationTtlDays,
      bm25IndexBucket: bm25IndexBucket,
      retrievalManifestParameterName,
      retrievalKnowledgeBaseIds: greenKnowledgeBaseId
        ? [greenKnowledgeBaseId]
        : undefined,
      retrievalBm25Buckets: greenProcessedBucket
        ? [greenProcessedBucket]
        : undefined,
      hydeEnabled: props.backend?.hydeEnabled,
      hydeModelId: props.backend?.hydeModelId,
      searchMode: props.backend?.searchMode,
      agentSearchIndexBucket: agentSearchIndexBucket,
      langfuseHost: props.backend?.langfuseHost,
      langfuseSecretName: props.backend?.langfuseSecretName,
      langfuseKeyRotatedAt: props.backend?.langfuseKeyRotatedAt,
      otelIncludeContent: props.backend?.otelIncludeContent,
      ecrAccount: props.ecrAccount,
    });

    if (props.backend?.searchMode === 'agent' && agentSearchIndexBucket) {
      const indexBucket = s3.Bucket.fromBucketName(
        this,
        'AgentSearchIndexBucket',
        agentSearchIndexBucket,
      );
      new s3deploy.BucketDeployment(this, 'AgentSearchIndexDeployment', {
        sources: [s3deploy.Source.asset('seed-data/agent-search-index')],
        destinationBucket: indexBucket,
        destinationKeyPrefix: 'agent-search-index/',
        prune: false,
        retainOnDelete: true,
        memoryLimit: 256,
      });
    }

    const cognitoAuthorizer =
      props.auth?.anonymousAccess === true
        ? undefined
        : new apigateway.CognitoUserPoolsAuthorizer(this, 'CognitoAuthorizer', {
            authorizerName: `${props.prefix}-cognito-authorizer-${props.envName}`,
            cognitoUserPools: [this.auth.userPool],
            identitySource: 'method.request.header.Authorization',
            resultsCacheTtl: Duration.minutes(5),
          });

    // Analytics always needs Cognito auth — RFC-0013 removes chat auth only, not dashboard auth.
    const analyticsAuthorizer =
      cognitoAuthorizer ??
      new apigateway.CognitoUserPoolsAuthorizer(
        this,
        'AnalyticsCognitoAuthorizer',
        {
          authorizerName: `${props.prefix}-analytics-cognito-authorizer-${props.envName}`,
          cognitoUserPools: [this.auth.userPool],
          identitySource: 'method.request.header.Authorization',
          resultsCacheTtl: Duration.minutes(5),
        },
      );

    this.apiGateway.addHealthLambdaIntegration(
      this.lambdaBackend.getHealthHandler(),
    );

    this.apiGateway.addChatLambdaIntegration(
      this.lambdaBackend.getChatHandler(),
      cognitoAuthorizer,
    );

    this.apiGateway.addAnalyticsLambdaIntegration(
      this.lambdaBackend.getAnalyticsHandler(),
      analyticsAuthorizer,
    );

    this.apiGateway.addConsentLambdaIntegration(
      this.lambdaBackend.getChatHandler(),
    );

    this.apiGateway.addSessionLambdaIntegration(
      this.lambdaBackend.getChatHandler(),
    );

    new CfnOutput(this, 'ApiUrl', {
      value: this.apiGateway.getApiUrl(),
      description: 'API Gateway URL',
      exportName: `${props.envName}-ApiUrl`,
    });

    new CfnOutput(this, 'ApiHealthEndpoint', {
      value: `${this.apiGateway.getApiUrl()}health`,
      description: 'Health check endpoint (no auth required)',
    });

    new CfnOutput(this, 'ApiChatEndpoint', {
      value: `${this.apiGateway.getApiUrl()}api/chat`,
      description: 'Chat endpoint (requires authentication)',
    });

    new CfnOutput(this, 'UserPoolId', {
      value: this.auth.userPool.userPoolId,
      description: 'Cognito User Pool ID',
      exportName: `${props.envName}-UserPoolId`,
    });

    new CfnOutput(this, 'UserPoolClientId', {
      value: this.auth.client.userPoolClientId,
      description: 'Cognito User Pool Client ID',
      exportName: `${props.envName}-UserPoolClientId`,
    });

    new CfnOutput(this, 'UserPoolDomain', {
      value: `https://${props.auth.userPoolDomainPrefix}.auth.${this.region}.amazoncognito.com`,
      description: 'Cognito User Pool Domain',
    });

    new CfnOutput(this, 'Region', {
      value: this.region,
      description: 'AWS Region',
    });

    let alertTopic;
    if (props.monitoring?.alertEmail || props.monitoring?.alertEmails?.length) {
      const alerting = new AlertingTopic(this, 'Alerting', {
        prefix: props.prefix,
        envName: props.envName,
        alertEmail: props.monitoring.alertEmail,
        alertEmails: props.monitoring.alertEmails,
      });
      alertTopic = alerting.topic;
    }

    // Maintenance reason (#579) — created in every env so maintenance-switch.sh
    // never hits a missing-parameter branch. Values: none | manual | budget.
    const maintenanceReasonParameter = new ssm.StringParameter(
      this,
      'MaintenanceReasonParameter',
      {
        parameterName: `/${props.envName}/renate/maintenance-reason`,
        stringValue: 'none',
        description:
          'Why maintenance mode is active: none | manual | budget (#579)',
      },
    );

    new CfnOutput(this, 'MaintenanceReasonParameterName', {
      value: maintenanceReasonParameter.parameterName,
      description: 'SSM parameter holding the maintenance reason',
    });

    const chatbotAlarms = new ChatbotAlarms(this, 'ChatbotAlarms', {
      prefix: props.prefix,
      envName: props.envName,
      chatLambda: this.lambdaBackend.getChatHandler(),
      healthLambda: this.lambdaBackend.getHealthHandler(),
      api: this.apiGateway.getApi(),
      alertTopic: alertTopic,
      chatLogGroup: this.lambdaBackend.chatLogGroup,
      lambdaErrorThreshold: 5,
      bedrockTokenAlarm: props.monitoring?.bedrockTokenAlarm,
    });

    // Budget Alerts (prod only — fixed 60k€/year budget).
    if (props.monitoring?.budget && alertTopic) {
      new BudgetAlerts(this, 'BudgetAlerts', {
        prefix: props.prefix,
        envName: props.envName,
        monthlyBudgetUsd: props.monitoring.budget.monthlyBudgetUsd,
        thresholds: props.monitoring.budget.thresholds,
        alertTopic: alertTopic,
      });
    }

    // Budget Pacing (#579) auto-flips to maintenance mode on daily overspend.
    // Guarded on alertTopic: silent cost-driven outage is worse than no pacing.
    if (props.monitoring?.enableBudgetPacing && alertTopic) {
      new BudgetPacing(this, 'BudgetPacing', {
        prefix: props.prefix,
        envName: props.envName,
        monthlyBudgetUsd: props.monitoring.budgetPacingMonthlyUsd ?? 7000,
        maintenanceKvsArn: this.frontend.maintenanceModeStoreArn,
        chatHandler: this.lambdaBackend.getChatHandler(),
        alertTopic: alertTopic,
        maintenanceReasonParameter: maintenanceReasonParameter,
        distributionId: this.frontend.cloudFrontWebDistribution.distributionId,
      });
    }

    let etlQueue: sqs.IQueue | undefined;
    let etlDlq: sqs.IQueue | undefined;
    let transformLambda: lambda.IFunction | undefined;
    let bm25BuilderLambda: lambda.IFunction | undefined;
    let bm25RebuildQueue: sqs.IQueue | undefined;
    let bm25RebuildDlq: sqs.IQueue | undefined;

    if (props.monitoring?.enableEtlMonitoring) {
      const etlQueueArn = ssm.StringParameter.valueForStringParameter(
        this,
        `/${props.envName}/renate/etl-queue-arn`,
      );
      const etlDlqArn = ssm.StringParameter.valueForStringParameter(
        this,
        `/${props.envName}/renate/etl-dlq-arn`,
      );
      const transformLambdaArn = ssm.StringParameter.valueForStringParameter(
        this,
        `/${props.envName}/renate/transform-lambda-arn`,
      );

      etlQueue = sqs.Queue.fromQueueArn(this, 'ImportedEtlQueue', etlQueueArn);
      etlDlq = sqs.Queue.fromQueueArn(this, 'ImportedEtlDlq', etlDlqArn);
      transformLambda = lambda.Function.fromFunctionArn(
        this,
        'ImportedTransformLambda',
        transformLambdaArn,
      );

      // BM25 builder widgets scoped to enableBm25 — SSM params only exist there.
      if (props.backend?.enableBm25) {
        const bm25BuilderLambdaArn =
          ssm.StringParameter.valueForStringParameter(
            this,
            `/${props.envName}/renate/bm25-builder-function-arn`,
          );
        const bm25RebuildQueueArn = ssm.StringParameter.valueForStringParameter(
          this,
          `/${props.envName}/renate/bm25-rebuild-queue-arn`,
        );
        const bm25RebuildDlqArn = ssm.StringParameter.valueForStringParameter(
          this,
          `/${props.envName}/renate/bm25-rebuild-dlq-arn`,
        );

        bm25BuilderLambda = lambda.Function.fromFunctionArn(
          this,
          'ImportedBm25BuilderLambda',
          bm25BuilderLambdaArn,
        );
        bm25RebuildQueue = sqs.Queue.fromQueueArn(
          this,
          'ImportedBm25RebuildQueue',
          bm25RebuildQueueArn,
        );
        bm25RebuildDlq = sqs.Queue.fromQueueArn(
          this,
          'ImportedBm25RebuildDlq',
          bm25RebuildDlqArn,
        );
      }
    }

    new MonitoringDashboard(this, 'MonitoringDashboard', {
      prefix: props.prefix,
      envName: props.envName,
      chatLambda: this.lambdaBackend.getChatHandler(),
      healthLambda: this.lambdaBackend.getHealthHandler(),
      transformLambda: transformLambda,
      api: this.apiGateway.getApi(),
      etlQueue: etlQueue,
      etlDlq: etlDlq,
      bm25BuilderLambda: bm25BuilderLambda,
      bm25RebuildQueue: bm25RebuildQueue,
      bm25RebuildDlq: bm25RebuildDlq,
      // QA + prod publish scheduled retrieval-health metrics (#494/#671);
      // preprod keeps alarms but no dashboard row.
      showRetrievalHealthMetrics:
        props.envName === 'qa' || props.envName === 'prod',
      retrievalHealthMetricNamespace: manifestManaged
        ? retrievalMetricNamespace(props.envName)
        : undefined,
      distributionId: this.frontend.cloudFrontWebDistribution.distributionId,
      knowledgeBaseId: knowledgeBaseId,
      bedrockModelId: props.backend?.bedrockModelId,
      conversationTableName: this.conversationTable.tableName,
      alarms: [
        chatbotAlarms.chatLambdaErrorAlarm,
        chatbotAlarms.chatLambdaDurationAlarm,
        chatbotAlarms.api5xxAlarm,
        chatbotAlarms.apiLatencyAlarm,
        ...(chatbotAlarms.guardrailViolationAlarm
          ? [chatbotAlarms.guardrailViolationAlarm]
          : []),
      ],
    });
  }
}
