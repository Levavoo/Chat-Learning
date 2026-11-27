import { Construct } from 'constructs';
import { CfnOutput, Duration, Stack, Tags } from 'aws-cdk-lib';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as logs from 'aws-cdk-lib/aws-logs';
import { IFunction } from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface ApiGatewayProps {
  readonly prefix: string;
  /** VPC for private integration via VPC Link. */
  readonly vpc: ec2.IVpc;
  readonly envName: string;
  /** @default envName */
  readonly stageName?: string;
  /** @default true */
  readonly enableLogging?: boolean;
  /** @default true */
  readonly enableTracing?: boolean;
  /** @default apigateway.Cors.ALL_ORIGINS */
  readonly allowedOrigins?: string[];
  /** Requests/sec. @default 10000 */
  readonly throttleRateLimit?: number;
  /** Concurrent requests. @default 5000 */
  readonly throttleBurstLimit?: number;
  /** POST /api/chat requests/sec. @default 200 */
  readonly chatThrottleRateLimit?: number;
  /** POST /api/chat concurrent. @default 400 */
  readonly chatThrottleBurstLimit?: number;
}

export class ApiGatewayConstruct extends Construct {
  readonly api: apigateway.RestApi;
  private readonly healthResource: apigateway.Resource;
  private readonly chatResource: apigateway.Resource;
  private readonly apiResource: apigateway.Resource;
  private readonly consentResource: apigateway.Resource;
  private readonly sessionResource: apigateway.Resource;
  private readonly stageName: string;

  constructor(scope: Construct, id: string, props: ApiGatewayProps) {
    super(scope, id);

    this.stageName = props.stageName ?? props.envName;
    const enableLogging = props.enableLogging !== false;
    const enableTracing = props.enableTracing !== false;

    let accessLogGroup: logs.LogGroup | undefined;
    let cloudWatchRole: iam.Role | undefined;

    if (enableLogging) {
      accessLogGroup = new logs.LogGroup(this, 'AccessLogs', {
        logGroupName: `/aws/apigateway/${props.prefix}-apigateway-${props.envName}`,
        retention: logs.RetentionDays.THREE_MONTHS,
      });

      cloudWatchRole = new iam.Role(this, 'CloudWatchRole', {
        assumedBy: new iam.ServicePrincipal('apigateway.amazonaws.com'),
        description: 'Role for API Gateway to write logs to CloudWatch',
      });

      cloudWatchRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'logs:CreateLogGroup',
            'logs:CreateLogStream',
            'logs:DescribeLogGroups',
            'logs:DescribeLogStreams',
            'logs:PutLogEvents',
            'logs:GetLogEvents',
            'logs:FilterLogEvents',
          ],
          resources: ['*'],
        }),
      );
    }

    const api = new apigateway.RestApi(this, 'Api', {
      restApiName: `${props.prefix}-api-${props.envName}`,
      description: 'API Gateway for Chatbot Backend Services',

      deployOptions: {
        stageName: this.stageName,
        ...(enableLogging && accessLogGroup
          ? {
              loggingLevel: apigateway.MethodLoggingLevel.INFO,
              dataTraceEnabled: true,
              accessLogDestination: new apigateway.LogGroupLogDestination(
                accessLogGroup,
              ),
              accessLogFormat:
                apigateway.AccessLogFormat.jsonWithStandardFields({
                  caller: true,
                  httpMethod: true,
                  ip: true,
                  protocol: true,
                  requestTime: true,
                  resourcePath: true,
                  responseLength: true,
                  status: true,
                  user: true,
                }),
            }
          : {}),
        tracingEnabled: enableTracing,
        throttlingRateLimit: props.throttleRateLimit || 10000,
        throttlingBurstLimit: props.throttleBurstLimit || 5000,
        methodOptions: {
          '/api/chat/POST': {
            throttlingRateLimit: props.chatThrottleRateLimit ?? 200,
            throttlingBurstLimit: props.chatThrottleBurstLimit ?? 400,
          },
          '/api/consent/POST': {
            throttlingRateLimit: 50,
            throttlingBurstLimit: 100,
          },
          '/health/GET': {
            throttlingRateLimit: 500,
            throttlingBurstLimit: 1000,
          },
        },
      },
      defaultCorsPreflightOptions: {
        allowOrigins: props.allowedOrigins || apigateway.Cors.ALL_ORIGINS,
        allowMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allowHeaders: [
          'Content-Type',
          'X-Amz-Date',
          // Drop once anonymous auth is flipped per-env (#479, RFC 0013 Phase 4b).
          'Authorization',
          'X-Api-Key',
          'X-Amz-Security-Token',
          'X-Amz-User-Agent',
        ],
        allowCredentials: false,
        maxAge: Duration.hours(1),
      },
      endpointConfiguration: {
        types: [apigateway.EndpointType.REGIONAL],
      },
      // We manage the CloudWatch role explicitly.
      cloudWatchRole: false,
      apiKeySourceType: apigateway.ApiKeySourceType.HEADER,
    });

    // 503 is shared across THROTTLED causes (organic throttle + maintenance-mode
    // reserved-concurrency=0). GatewayResponse is global to the stage; on-call
    // must disambiguate via the maintenance KVS flag.
    // Origin='*' is spec-safe here because allowCredentials is false (two
    // configured origins mean we cannot hardcode one).
    api.addGatewayResponse('ThrottledGatewayResponse', {
      type: apigateway.ResponseType.THROTTLED,
      statusCode: '503',
      responseHeaders: {
        'Access-Control-Allow-Origin': "'*'",
      },
      templates: {
        'application/json': JSON.stringify({
          message: 'Service temporarily unavailable',
        }),
      },
    });

    // Reserved-concurrency=0 throws TooManyRequestsException on invoke, which
    // API Gateway reports as INTEGRATION_FAILURE (default 500) — map to 503.
    api.addGatewayResponse('IntegrationFailureGatewayResponse', {
      type: apigateway.ResponseType.INTEGRATION_FAILURE,
      statusCode: '503',
      responseHeaders: {
        'Access-Control-Allow-Origin': "'*'",
      },
      templates: {
        'application/json': JSON.stringify({
          message: 'Service temporarily unavailable',
        }),
      },
    });

    // Explicit CfnAccount avoids CDK's default fromAwsManagedPolicyName role.
    if (cloudWatchRole) {
      const cfnAccount = new apigateway.CfnAccount(this, 'ApiGatewayAccount', {
        cloudWatchRoleArn: cloudWatchRole.roleArn,
      });
      cfnAccount.node.addDependency(cloudWatchRole);
    }

    const healthResource = api.root.addResource('health');
    const apiResource = api.root.addResource('api');
    const chatResource = apiResource.addResource('chat');
    const consentResource = apiResource.addResource('consent');
    const sessionResource = apiResource
      .addResource('session')
      .addResource('{conversationId}');

    this.api = api;
    this.healthResource = healthResource;
    this.chatResource = chatResource;
    this.apiResource = apiResource;
    this.consentResource = consentResource;
    this.sessionResource = sessionResource;

    if (props.envName) {
      Tags.of(api).add('Environment', props.envName);
    }
    Tags.of(api).add('Project', 'DigiBro-Chatbot');
    Tags.of(api).add('ManagedBy', 'CDK');

    new CfnOutput(this, 'ApiGatewayUrl', {
      value: api.url,
      description: 'API Gateway URL',
      exportName: `${props.envName || 'default'}-ApiGatewayUrl`,
    });

    new CfnOutput(this, 'ApiGatewayId', {
      value: api.restApiId,
      description: 'API Gateway REST API ID',
      exportName: `${props.envName || 'default'}-ApiGatewayId`,
    });

    new CfnOutput(this, 'ApiStageName', {
      value: this.stageName,
      description: 'API Gateway stage name (read by apigateway-redeploy.sh)',
    });

    new CfnOutput(this, 'ApiGatewayRootResourceId', {
      value: api.root.resourceId,
      description: 'API Gateway root resource ID',
    });

    new CfnOutput(this, 'HealthEndpoint', {
      value: `${api.url}health`,
      description: 'Health check endpoint URL',
    });

    new CfnOutput(this, 'ChatEndpoint', {
      value: `${api.url}api/chat`,
      description: 'Chat API endpoint URL',
    });

    new CfnOutput(this, 'ConsentEndpoint', {
      value: `${api.url}api/consent`,
      description: 'Consent API endpoint URL (no auth)',
    });

    new CfnOutput(this, 'SessionEndpoint', {
      value: `${api.url}api/session/{conversationId}`,
      description: 'Session delete endpoint URL (no auth)',
    });

    new CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'API Gateway base URL (for maintenance-switch)',
    });

    if (accessLogGroup) {
      new CfnOutput(this, 'AccessLogGroupName', {
        value: accessLogGroup.logGroupName,
        description: 'CloudWatch Log Group for API Gateway access logs',
      });
    }
  }

  getApi(): apigateway.RestApi {
    return this.api;
  }

  getHealthResource(): apigateway.Resource {
    return this.healthResource;
  }

  getChatResource(): apigateway.Resource {
    return this.chatResource;
  }

  /** Routes /api/chat and /api/chat/{session_id}/feedback. */
  addChatLambdaIntegration(
    chatHandler: IFunction,
    authorizer?: apigateway.IAuthorizer,
  ): void {
    const integration = new apigateway.LambdaIntegration(chatHandler, {
      proxy: true,
    });

    const authConfig = {
      authorizationType: authorizer
        ? apigateway.AuthorizationType.COGNITO
        : apigateway.AuthorizationType.NONE,
      authorizer,
    };

    this.chatResource.addMethod('POST', integration, authConfig);

    const sessionResource = this.chatResource.addResource('{session_id}');
    const feedbackResource = sessionResource.addResource('feedback');
    feedbackResource.addMethod('ANY', integration, authConfig);
  }

  /**
   * Analytics (RFC-0009). Authorizer mandatory — endpoint stays authenticated
   * even when chat path is anonymous (RFC-0013 removes chat auth only).
   */
  addAnalyticsLambdaIntegration(
    analyticsHandler: IFunction,
    authorizer: apigateway.IAuthorizer,
  ): void {
    const integration = new apigateway.LambdaIntegration(analyticsHandler, {
      proxy: true,
    });

    const authConfig = {
      authorizationType: apigateway.AuthorizationType.COGNITO,
      authorizer,
    };

    const analyticsResource = this.apiResource.addResource('analytics');
    analyticsResource.addMethod('GET', integration, authConfig);

    const analyticsDocumentsResource = analyticsResource.addResource('documents');
    analyticsDocumentsResource.addMethod('GET', integration, authConfig);
  }

  addHealthLambdaIntegration(healthHandler: IFunction): void {
    const integration = new apigateway.LambdaIntegration(healthHandler, {
      proxy: true,
    });

    this.healthResource.addMethod('GET', integration, {
      methodResponses: [
        {
          statusCode: '200',
        },
      ],
      authorizationType: apigateway.AuthorizationType.NONE,
    });
  }

  /** POST /api/consent — unauthenticated. */
  addConsentLambdaIntegration(handler: IFunction): void {
    const integration = new apigateway.LambdaIntegration(handler, {
      proxy: true,
    });

    this.consentResource.addMethod('POST', integration, {
      authorizationType: apigateway.AuthorizationType.NONE,
    });
  }

  /** DELETE /api/session/{conversationId} — capability-based auth via UUID possession. */
  addSessionLambdaIntegration(handler: IFunction): void {
    const integration = new apigateway.LambdaIntegration(handler, {
      proxy: true,
    });

    this.sessionResource.addMethod('DELETE', integration, {
      authorizationType: apigateway.AuthorizationType.NONE,
    });
  }

  /** Constructed manually to avoid circular dep with the deployment. */
  getApiUrl(): string {
    const region = Stack.of(this).region;
    return `https://${this.api.restApiId}.execute-api.${region}.amazonaws.com/${this.stageName}/`;
  }

  getStageName(): string {
    return this.stageName;
  }

  /** execute-api domain (no protocol/path) for CloudFront origin. */
  getApiDomain(): string {
    const region = Stack.of(this).region;
    return `${this.api.restApiId}.execute-api.${region}.amazonaws.com`;
  }
}
