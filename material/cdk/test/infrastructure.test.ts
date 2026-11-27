import { App } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { ChatbotStack } from '../lib/chatbot-stack';

describe('ChatbotStack', () => {
  let app: App;
  let template: Template;

  beforeEach(() => {
    app = new App();
    const stack = new ChatbotStack(app, 'TestStack', {
      prefix: 'test',
      envName: 'dev',
      ecrAccount: '123456789012',
      frontend: {
        origin: 'http://localhost:4200',
      },
      auth: {
        userPoolDomainPrefix: 'test-chatbot-dev',
      },
      env: {
        account: '123456789012',
        region: 'eu-central-1',
      },
    });
    template = Template.fromStack(stack);
  });

  describe('Stack Creation', () => {
    test('should have correct stack outputs', () => {
      template.hasOutput('ApiUrl', {
        Export: { Name: 'dev-ApiUrl' },
      });

      template.hasOutput('UserPoolId', {
        Export: { Name: 'dev-UserPoolId' },
      });

      template.hasOutput('UserPoolClientId', {
        Export: { Name: 'dev-UserPoolClientId' },
      });
    });
  });

  describe('VPC Configuration', () => {
    test('should create VPC with correct CIDR', () => {
      template.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '10.0.0.0/16',
        EnableDnsHostnames: true,
        EnableDnsSupport: true,
      });
    });
  });

  describe('Cognito User Pool', () => {
    test('should create user pool with correct configuration', () => {
      template.hasResourceProperties('AWS::Cognito::UserPool', {
        UserPoolName: 'test-pool-dev',
        Policies: {
          PasswordPolicy: {
            MinimumLength: 8,
            RequireUppercase: true,
            RequireSymbols: true,
            RequireNumbers: true,
          },
        },
        AutoVerifiedAttributes: ['email'],
      });
    });
  });

  describe('API Gateway', () => {
    test('should create REST API', () => {
      template.hasResourceProperties('AWS::ApiGateway::RestApi', {
        Name: 'test-api-dev',
        Description: 'API Gateway for Chatbot Backend Services',
        EndpointConfiguration: {
          Types: ['REGIONAL'],
        },
      });
    });
  });

  describe('Lambda Functions', () => {
    test('should deploy Lambda in VPC', () => {
      const lambdaFunctions = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: Match.stringLikeRegexp('test-(chat|health)-dev'),
        },
      });

      Object.values(lambdaFunctions).forEach((fn: any) => {
        expect(fn.Properties.VpcConfig).toBeDefined();
      });
    });

    test('should enable X-Ray tracing for Lambda', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        TracingConfig: {
          Mode: 'Active',
        },
      });
    });
  });

  describe('CloudFront Distribution', () => {
    test('should use CloudFront Function for SPA routing', () => {
      template.hasResourceProperties('AWS::CloudFront::Function', {
        FunctionConfig: {
          Runtime: 'cloudfront-js-2.0',
        },
      });
    });
  });

  describe('S3 Buckets', () => {
    test('should create asset bucket', () => {
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: 'test-assets-dev-eu-central-1',
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: {
                SSEAlgorithm: 'AES256',
              },
            },
          ],
        },
        PublicAccessBlockConfiguration: {
          BlockPublicAcls: true,
          BlockPublicPolicy: true,
          IgnorePublicAcls: true,
          RestrictPublicBuckets: true,
        },
      });
    });
  });

  describe('IAM Roles and Permissions', () => {
    test('should grant Bedrock permissions to chat handler', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: [
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream',
                'bedrock:Converse',
              ],
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });
  });

  describe('CloudWatch Logs', () => {
    test('should create log groups for Lambda functions', () => {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-chat-dev',
        RetentionInDays: 7,
      });

      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-health-dev',
        RetentionInDays: 7,
      });
    });
  });

  describe('Integration Tests', () => {
    test('should wire API Gateway to Lambda functions', () => {
      const methods = template.findResources('AWS::ApiGateway::Method', {
        Properties: {
          HttpMethod: Match.anyValue(),
          Integration: {
            Type: 'AWS_PROXY',
          },
        },
      });
      expect(Object.keys(methods).length).toBeGreaterThanOrEqual(2);
    });

    test('should configure Cognito authorizer for chat endpoint', () => {
      template.hasResourceProperties('AWS::ApiGateway::Authorizer', {
        Type: 'COGNITO_USER_POOLS',
        IdentitySource: 'method.request.header.Authorization',
      });
    });

    test('should have health endpoint without auth', () => {
      const healthMethods = template.findResources('AWS::ApiGateway::Method');
      let hasUnauthenticatedHealthEndpoint = false;

      Object.values(healthMethods).forEach((method: any) => {
        if (
          method.Properties.HttpMethod === 'GET' &&
          method.Properties.AuthorizationType === 'NONE'
        ) {
          hasUnauthenticatedHealthEndpoint = true;
        }
      });

      expect(hasUnauthenticatedHealthEndpoint).toBe(true);
    });
  });

  describe('Resource Tagging', () => {
    test('should tag VPC resources', () => {
      const vpcs = template.findResources('AWS::EC2::VPC');
      Object.values(vpcs).forEach((vpc: any) => {
        const tags = vpc.Properties.Tags || [];
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Environment).toBe('dev');
        expect(tagMap.Project).toBe('DigiBro-Chatbot');
        expect(tagMap.ManagedBy).toBe('CDK');
      });
    });

    test('should tag Lambda functions', () => {
      const lambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: Match.stringLikeRegexp('test-(chat|health)-dev'),
        },
      });
      Object.values(lambdas).forEach((lambda: any) => {
        const tags = lambda.Properties.Tags || [];
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Project).toBe('DigiBro-Chatbot');
        expect(tagMap.Environment).toBe('dev');
      });
    });
  });

  describe('Stack Configuration Variations', () => {
    test('should create stack with custom VPC CIDR', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'CustomVpcStack', {
        prefix: 'custom',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'http://localhost:4200',
        },
        auth: {
          userPoolDomainPrefix: 'custom-test',
        },
        network: {
          vpcCidr: '172.16.0.0/16',
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const customTemplate = Template.fromStack(customStack);
      customTemplate.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '172.16.0.0/16',
      });
    });

    test('should create stack with custom Lambda timeout', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'CustomLambdaStack', {
        prefix: 'custom',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'http://localhost:4200',
        },
        auth: {
          userPoolDomainPrefix: 'custom-test',
        },
        backend: {
          lambdaTimeout: 60,
          lambdaMemorySize: 1024,
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const customTemplate = Template.fromStack(customStack);
      customTemplate.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'custom-chat-test',
        Timeout: 60,
        MemorySize: 1024,
      });
    });

    test('should create stack with email domain restrictions', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'EmailRestrictedStack', {
        prefix: 'restricted',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'http://localhost:4200',
        },
        auth: {
          userPoolDomainPrefix: 'restricted-test',
          allowedSignUpEmailDomains: ['example.com', 'test.com'],
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const customTemplate = Template.fromStack(customStack);
      customTemplate.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'restricted-email-check-test',
        Environment: {
          Variables: {
            ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR: '["example.com","test.com"]',
          },
        },
      });
    });

    test('should disable self-signup when configured', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'NoSelfSignupStack', {
        prefix: 'nosignup',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'http://localhost:4200',
        },
        auth: {
          userPoolDomainPrefix: 'nosignup-test',
          selfSignUpEnabled: false,
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const customTemplate = Template.fromStack(customStack);
      customTemplate.resourceCountIs('AWS::Cognito::UserPool', 1);
    });

    test('should create stack for production environment', () => {
      const prodApp = new App();
      const prodStack = new ChatbotStack(prodApp, 'ProdStack', {
        prefix: 'prod',
        envName: 'production',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'https://chat.example.com',
        },
        auth: {
          userPoolDomainPrefix: 'prod-chatbot',
        },
        network: {
          maxAzs: 3,
          natGateways: 2,
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const prodTemplate = Template.fromStack(prodStack);

      prodTemplate.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/prod-chat-production',
        RetentionInDays: 30,
      });

      prodTemplate.resourceCountIs('AWS::EC2::NatGateway', 2);
    });

    test('should disable tracing when configured', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'NoTracingStack', {
        prefix: 'notrace',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: {
          origin: 'http://localhost:4200',
        },
        auth: {
          userPoolDomainPrefix: 'notrace-test',
        },
        backend: {
          enableTracing: false,
        },
        env: {
          account: '123456789012',
          region: 'eu-central-1',
        },
      });

      const customTemplate = Template.fromStack(customStack);
      const lambdas = customTemplate.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'notrace-chat-test',
        },
      });
      const lambda = Object.values(lambdas)[0] as any;
      expect(lambda.Properties.TracingConfig?.Mode).not.toBe('Active');

      customTemplate.hasResourceProperties('AWS::ApiGateway::Stage', {
        TracingEnabled: false,
      });
    });

    test('should include ETL SSM references in template when enableEtlMonitoring is true', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'EtlMonitoringOnStack', {
        prefix: 'test',
        envName: 'dev',
        ecrAccount: '123456789012',
        frontend: { origin: 'http://localhost:4200' },
        auth: { userPoolDomainPrefix: 'test-dev' },
        monitoring: { enableEtlMonitoring: true },
        env: { account: '123456789012', region: 'eu-central-1' },
      });
      const templateJson = JSON.stringify(
        Template.fromStack(customStack).toJSON(),
      );
      expect(templateJson).toContain('/dev/renate/etl-queue-arn');
      expect(templateJson).toContain('/dev/renate/etl-dlq-arn');
      expect(templateJson).toContain('/dev/renate/transform-lambda-arn');
    });

    test('should not include ETL SSM references in template when enableEtlMonitoring is false', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'EtlMonitoringOffStack', {
        prefix: 'test',
        envName: 'dev',
        ecrAccount: '123456789012',
        frontend: { origin: 'http://localhost:4200' },
        auth: { userPoolDomainPrefix: 'test-dev' },
        monitoring: { enableEtlMonitoring: false },
        env: { account: '123456789012', region: 'eu-central-1' },
      });
      const templateJson = JSON.stringify(
        Template.fromStack(customStack).toJSON(),
      );
      expect(templateJson).not.toContain('/dev/renate/etl-queue-arn');
      expect(templateJson).not.toContain('/dev/renate/etl-dlq-arn');
      expect(templateJson).not.toContain('/dev/renate/transform-lambda-arn');
    });

    test('should omit Cognito authorizer for chat but keep one for analytics when anonymousAccess is true', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'NoAuthorizerStack', {
        prefix: 'noauth',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: { origin: 'http://localhost:4200' },
        auth: { userPoolDomainPrefix: 'noauth-test', anonymousAccess: true },
        env: { account: '123456789012', region: 'eu-central-1' },
      });

      const customTemplate = Template.fromStack(customStack);
      // RFC-0009: analytics route keeps a Cognito authorizer even when the chat
      // authorizer flag is disabled — RFC-0013 removes chat auth, not dashboard.
      customTemplate.resourceCountIs('AWS::ApiGateway::Authorizer', 1);
    });

    test('should keep chat endpoint wired when anonymousAccess is true', () => {
      const customApp = new App();
      const customStack = new ChatbotStack(customApp, 'NoAuthorizerChatStack', {
        prefix: 'noauthchat',
        envName: 'test',
        ecrAccount: '123456789012',
        frontend: { origin: 'http://localhost:4200' },
        auth: {
          userPoolDomainPrefix: 'noauthchat-test',
          anonymousAccess: true,
        },
        env: { account: '123456789012', region: 'eu-central-1' },
      });

      const customTemplate = Template.fromStack(customStack);
      const methods = customTemplate.findResources('AWS::ApiGateway::Method', {
        Properties: {
          HttpMethod: 'POST',
          Integration: { Type: 'AWS_PROXY' },
        },
      });
      expect(Object.keys(methods).length).toBeGreaterThanOrEqual(1);
    });
  });
});

describe('#668 — prod chatbot manifest-managed wiring', () => {
  function buildProdChatbotTemplate(): Template {
    const prodApp = new App({
      context: { env: 'prod', environment: 'prod' },
    });
    const stack = new ChatbotStack(prodApp, 'ProdManifestChatbotStack', {
      prefix: 'renate',
      envName: 'prod',
      ecrAccount: '123456789012',
      frontend: { origin: 'http://localhost:4200' },
      auth: { userPoolDomainPrefix: 'renate-chatbot-prod' },
      backend: { enableBm25: true },
      env: { account: '123456789012', region: 'eu-central-1' },
    });
    return Template.fromStack(stack);
  }

  let prodTemplate: Template;
  beforeAll(() => {
    prodTemplate = buildProdChatbotTemplate();
  });

  test('resolves both green retrieval slot coordinates at deploy time', () => {
    const serialized = JSON.stringify(prodTemplate.toJSON());
    expect(serialized).toContain(
      '/prod/renate/retrieval/slots/green/knowledge-base-id',
    );
    expect(serialized).toContain(
      '/prod/renate/retrieval/slots/green/processed-bucket-name',
    );
  });

  test('passes the active-manifest selector NAME to the Lambda without creating or importing the selector', () => {
    // The runtime selector is a parameter NAME handed to the Lambda; #668 must
    // NOT create the selector (that is #669's baseline step).
    prodTemplate.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          RETRIEVAL_MANIFEST_PARAMETER:
            '/prod/renate/retrieval/active-manifest',
        }),
      },
    });

    const selectors = prodTemplate.findResources('AWS::SSM::Parameter', {
      Properties: { Name: '/prod/renate/retrieval/active-manifest' },
    });
    expect(Object.keys(selectors)).toHaveLength(0);

    const templateParameters = prodTemplate.toJSON().Parameters ?? {};
    const selectorImports = Object.values(templateParameters).filter(
      (parameter: any) =>
        parameter.Type === 'AWS::SSM::Parameter::Value<String>' &&
        parameter.Default === '/prod/renate/retrieval/active-manifest',
    );
    expect(selectorImports).toHaveLength(0);
  });

  test('renders the prod retrieval-health metrics on the monitoring dashboard', () => {
    const serialized = JSON.stringify(prodTemplate.toJSON());
    expect(serialized).toContain('Retrieval Health');
    expect(serialized).toContain('Renate/Prod/Retrieval');
    expect(serialized).toContain('CheckExecuted');
  });
});
