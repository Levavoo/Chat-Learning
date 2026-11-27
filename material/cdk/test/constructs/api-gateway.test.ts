import { App, Stack, Duration } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ApiGatewayConstruct } from '../../lib/constructs/api-gateway';
import { Vpc } from 'aws-cdk-lib/aws-ec2';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';

describe('ApiGatewayConstruct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;
  let vpc: Vpc;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });

    vpc = new Vpc(stack, 'TestVpc', {
      maxAzs: 2,
    });
  });

  describe('REST API Creation', () => {
    test('should create REST API with correct name', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::RestApi', {
        Name: 'test-api-dev',
        Description: 'API Gateway for Chatbot Backend Services',
      });
    });

    test('should configure regional endpoint', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::RestApi', {
        EndpointConfiguration: {
          Types: ['REGIONAL'],
        },
      });
    });
  });

  describe('API Resources', () => {
    test('should create health resource', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: 'health',
      });
    });

    test('should create api resource', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: 'api',
      });
    });

    test('should create chat resource under api', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: 'chat',
      });
    });
  });

  describe('CORS Configuration', () => {
    test('should configure CORS with default origins', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      const methods = template.findResources('AWS::ApiGateway::Method', {
        Properties: {
          HttpMethod: 'OPTIONS',
        },
      });
      expect(Object.keys(methods).length).toBeGreaterThan(0);
    });

    test('should configure CORS with custom origins', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        allowedOrigins: ['https://example.com'],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'OPTIONS',
        Integration: {
          IntegrationResponses: Match.arrayWith([
            Match.objectLike({
              ResponseParameters: Match.objectLike({
                'method.response.header.Access-Control-Allow-Origin':
                  "'https://example.com'",
              }),
            }),
          ]),
        },
      });
    });

    test('should allow required headers including Authorization until #479', () => {
      // Authorization stays in allowHeaders until the JWT authorizer is removed
      // per env (RFC 0013 Phase 4b); Angular + Cognito still send it.
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'OPTIONS',
        Integration: {
          IntegrationResponses: Match.arrayWith([
            Match.objectLike({
              ResponseParameters: Match.objectLike({
                'method.response.header.Access-Control-Allow-Headers':
                  Match.stringLikeRegexp('.*Authorization.*'),
              }),
            }),
          ]),
        },
      });
    });

    test('should set allowCredentials to false', () => {
      // Spec compliance: Access-Control-Allow-Credentials must not be true
      // when Access-Control-Allow-Origin is '*' or a list. RFC 0013 removes
      // credentials entirely, so this must be false in every env.
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        allowedOrigins: ['https://example.com'],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'OPTIONS',
        Integration: {
          IntegrationResponses: Match.arrayWith([
            Match.objectLike({
              ResponseParameters: Match.objectLike({
                'method.response.header.Access-Control-Allow-Credentials':
                  Match.absent(),
              }),
            }),
          ]),
        },
      });
    });

    test('should set gateway response CORS origin to wildcard', () => {
      // GatewayResponse headers are static; two configured origins
      // (frontend + CloudFront) can't both be hardcoded. '*' is
      // spec-compliant here because allowCredentials is false.
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        allowedOrigins: [
          'https://frontend.example.com',
          'https://cloudfront.example.com',
        ],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::GatewayResponse', {
        ResponseType: 'THROTTLED',
        ResponseParameters: {
          'gatewayresponse.header.Access-Control-Allow-Origin': "'*'",
        },
      });
      template.hasResourceProperties('AWS::ApiGateway::GatewayResponse', {
        ResponseType: 'INTEGRATION_FAILURE',
        ResponseParameters: {
          'gatewayresponse.header.Access-Control-Allow-Origin': "'*'",
        },
      });
    });
  });

  describe('Deployment Configuration', () => {
    test('should default stage name to envName', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        StageName: 'dev',
      });
    });

    test('should emit ApiStageName CfnOutput matching the stage', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'preprod',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Value: 'preprod',
        Description: Match.stringLikeRegexp('apigateway-redeploy'),
      });
    });

    test('should use custom stage name when specified', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        stageName: 'v1',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        StageName: 'v1',
      });
    });

    test('should configure throttling with defaults', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            ThrottlingRateLimit: 10000,
            ThrottlingBurstLimit: 5000,
          }),
        ]),
      });
    });

    test('should configure custom throttling limits', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        throttleRateLimit: 5000,
        throttleBurstLimit: 2500,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            ThrottlingRateLimit: 5000,
            ThrottlingBurstLimit: 2500,
          }),
        ]),
      });
    });

    test('should configure per-method throttling for POST /api/chat with defaults', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            HttpMethod: 'POST',
            ResourcePath: '/~1api~1chat',
            ThrottlingRateLimit: 200,
            ThrottlingBurstLimit: 400,
          }),
        ]),
      });
    });

    test('should configure per-method throttling for GET /health', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            HttpMethod: 'GET',
            ResourcePath: '/~1health',
            ThrottlingRateLimit: 500,
            ThrottlingBurstLimit: 1000,
          }),
        ]),
      });
    });

    test('should configure custom per-method throttling for POST /api/chat', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        chatThrottleRateLimit: 50,
        chatThrottleBurstLimit: 100,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            HttpMethod: 'POST',
            ResourcePath: '/~1api~1chat',
            ThrottlingRateLimit: 50,
            ThrottlingBurstLimit: 100,
          }),
        ]),
      });
    });
  });

  describe('Gateway Responses', () => {
    test('should remap THROTTLED responses to HTTP 503', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::GatewayResponse', {
        ResponseType: 'THROTTLED',
        StatusCode: '503',
      });
    });

    test('should remap INTEGRATION_FAILURE responses to HTTP 503', () => {
      // Lambda reserved concurrency = 0 (maintenance mode) makes the Lambda
      // invoke itself throttle (TooManyRequestsException), which API Gateway
      // classifies as INTEGRATION_FAILURE, not THROTTLED — THROTTLED only
      // covers API Gateway's own usage-plan/method/stage/account throttling.
      // Unmapped, INTEGRATION_FAILURE falls back to a plain 500.
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::GatewayResponse', {
        ResponseType: 'INTEGRATION_FAILURE',
        StatusCode: '503',
      });
    });
  });

  describe('CloudWatch Logging', () => {
    test('should create log group by default', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/apigateway/test-apigateway-dev',
        RetentionInDays: 90,
      });
    });

    test('should enable access logging by default', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        AccessLogSetting: Match.objectLike({
          Format: Match.stringLikeRegexp('.*requestTime.*'),
        }),
      });
    });

    test('should enable method logging by default', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            LoggingLevel: 'INFO',
            DataTraceEnabled: true,
          }),
        ]),
      });
    });

    test('should skip logging when disabled', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        enableLogging: false,
      });

      template = Template.fromStack(stack);
      const logGroups = template.findResources('AWS::Logs::LogGroup', {
        Properties: {
          LogGroupName: '/aws/apigateway/test-apigateway-dev',
        },
      });
      expect(Object.keys(logGroups).length).toBe(0);
    });
  });

  describe('X-Ray Tracing', () => {
    test('should enable tracing by default', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        TracingEnabled: true,
      });
    });

    test('should disable tracing when configured', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        enableTracing: false,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        TracingEnabled: false,
      });
    });
  });

  describe('IAM Roles', () => {
    test('should create CloudWatch role for logging', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: {
                Service: 'apigateway.amazonaws.com',
              },
            }),
          ]),
        }),
      });
    });

    test('should grant CloudWatch Logs permissions', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith([
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
              ]),
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });
  });

  describe('Lambda Integration', () => {
    test('should add health Lambda integration', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const healthLambda = new lambda.Function(stack, 'HealthFunction', {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: 'index.handler',
        code: lambda.Code.fromInline('def handler(event, context): return {}'),
      });

      apiGw.addHealthLambdaIntegration(healthLambda);

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'GET',
        AuthorizationType: 'NONE',
      });
    });

    test('should add chat Lambda integration without auth', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const chatLambda = new lambda.Function(stack, 'ChatFunction', {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: 'index.handler',
        code: lambda.Code.fromInline('def handler(event, context): return {}'),
      });

      apiGw.addChatLambdaIntegration(chatLambda);

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'POST',
        AuthorizationType: 'NONE',
      });
    });

    test('should add chat Lambda integration with Cognito authorizer', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const chatLambda = new lambda.Function(stack, 'ChatFunction', {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: 'index.handler',
        code: lambda.Code.fromInline('def handler(event, context): return {}'),
      });

      const authorizer = new apigateway.CognitoUserPoolsAuthorizer(
        stack,
        'Authorizer',
        {
          cognitoUserPools: [],
        },
      );

      apiGw.addChatLambdaIntegration(chatLambda, authorizer);

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Method', {
        HttpMethod: 'POST',
        AuthorizationType: 'COGNITO_USER_POOLS',
      });
    });
  });

  describe('Getter Methods', () => {
    test('should return API instance', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const api = apiGw.getApi();
      expect(api).toBeDefined();
      expect(api.restApiId).toBeDefined();
    });

    test('should return health resource', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const healthResource = apiGw.getHealthResource();
      expect(healthResource).toBeDefined();
      expect(healthResource.path).toContain('health');
    });

    test('should return chat resource', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const chatResource = apiGw.getChatResource();
      expect(chatResource).toBeDefined();
      expect(chatResource.path).toContain('chat');
    });

    test('should return API URL', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
        stageName: 'v1',
      });

      const apiUrl = apiGw.getApiUrl();
      expect(apiUrl).toBeDefined();
      expect(apiUrl).toContain('execute-api');
      expect(apiUrl).toContain('eu-central-1');
      expect(apiUrl).toContain('/v1/');
    });
  });

  describe('Outputs', () => {
    test('should export API Gateway URL', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'API Gateway URL',
        Export: { Name: 'dev-ApiGatewayUrl' },
      });
    });

    test('should export API Gateway ID', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'API Gateway REST API ID',
        Export: { Name: 'dev-ApiGatewayId' },
      });
    });

    test('should output health endpoint URL', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Health check endpoint URL',
      });
    });

    test('should output chat endpoint URL', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Chat API endpoint URL',
      });
    });

    test('should output access log group name', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'CloudWatch Log Group for API Gateway access logs',
      });
    });
  });

  describe('Resource Tagging', () => {
    test('should tag API Gateway resources', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      const apis = template.findResources('AWS::ApiGateway::RestApi');
      Object.values(apis).forEach((api: any) => {
        const tags = api.Properties.Tags || [];
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Environment).toBe('dev');
        expect(tagMap.Project).toBe('DigiBro-Chatbot');
        expect(tagMap.ManagedBy).toBe('CDK');
      });
    });
  });

  describe('Consent Endpoint', () => {
    test('should create consent resource under api', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: 'consent',
      });
    });

    test('should add consent Lambda integration with no auth', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const consentLambda = new lambda.Function(stack, 'ConsentFunction', {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: 'index.handler',
        code: lambda.Code.fromInline('def handler(event, context): return {}'),
      });

      apiGw.addConsentLambdaIntegration(consentLambda);

      template = Template.fromStack(stack);
      const methods = template.findResources('AWS::ApiGateway::Method', {
        Properties: {
          HttpMethod: 'POST',
          AuthorizationType: 'NONE',
        },
      });
      expect(Object.keys(methods).length).toBeGreaterThan(0);
    });

    test('should configure per-method throttling for POST /api/consent', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        MethodSettings: Match.arrayWith([
          Match.objectLike({
            HttpMethod: 'POST',
            ResourcePath: '/~1api~1consent',
            ThrottlingRateLimit: 50,
            ThrottlingBurstLimit: 100,
          }),
        ]),
      });
    });

    test('should output consent endpoint URL', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Consent API endpoint URL (no auth)',
      });
    });
  });

  describe('Session Delete Endpoint', () => {
    test('should create session resource with path parameter', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: 'session',
      });
      template.hasResourceProperties('AWS::ApiGateway::Resource', {
        PathPart: '{conversationId}',
      });
    });

    test('should add session Lambda integration with no auth', () => {
      const apiGw = new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      const sessionLambda = new lambda.Function(stack, 'SessionFunction', {
        runtime: lambda.Runtime.PYTHON_3_13,
        handler: 'index.handler',
        code: lambda.Code.fromInline('def handler(event, context): return {}'),
      });

      apiGw.addSessionLambdaIntegration(sessionLambda);

      template = Template.fromStack(stack);
      const methods = template.findResources('AWS::ApiGateway::Method', {
        Properties: {
          HttpMethod: 'DELETE',
          AuthorizationType: 'NONE',
        },
      });
      expect(Object.keys(methods).length).toBeGreaterThan(0);
    });

    test('should output session endpoint URL', () => {
      new ApiGatewayConstruct(stack, 'TestApiGateway', {
        prefix: 'test',
        vpc,
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Session delete endpoint URL (no auth)',
      });
    });
  });
});
