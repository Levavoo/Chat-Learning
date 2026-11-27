import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { LambdaBackend } from '../../lib/constructs/lambda-backend';
import { Vpc, SecurityGroup } from 'aws-cdk-lib/aws-ec2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as lambda from 'aws-cdk-lib/aws-lambda';

const DEV_ECR_ACCOUNT = '123456789012';

describe('LambdaBackend Construct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;
  let vpc: Vpc;
  let securityGroup: SecurityGroup;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });

    vpc = new Vpc(stack, 'TestVpc', {
      maxAzs: 2,
    });

    securityGroup = new SecurityGroup(stack, 'TestSecurityGroup', {
      vpc,
      description: 'Test security group',
    });
  });

  describe('ECR Image Source', () => {
    test('does not create ECR repository — Terraform owns it', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::ECR::Repository', 0);
    });

    test('chat handler image URI references dev ECR repo', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Code: {
          ImageUri: Match.objectLike({
            'Fn::Join': Match.arrayWith([
              '',
              Match.arrayWith([Match.stringLikeRegexp('test-chat-lambda')]),
            ]),
          }),
        },
      });
    });

    test('chat handler image tag resolves from SSM /dev/renate/image-tag', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasParameter('*', {
        Type: 'AWS::SSM::Parameter::Value<String>',
        Default: '/dev/renate/image-tag',
      });
    });

    test('chatbotImageTag context pins the exact immutable image without SSM', () => {
      const contextApp = new App({ context: { chatbotImageTag: '1.112.7' } });
      const contextStack = new Stack(contextApp, 'PinnedChatbotStack', {
        env: { account: '123456789012', region: 'eu-central-1' },
      });
      const contextVpc = new Vpc(contextStack, 'Vpc', { maxAzs: 2 });
      const contextSecurityGroup = new SecurityGroup(
        contextStack,
        'SecurityGroup',
        { vpc: contextVpc },
      );

      new LambdaBackend(contextStack, 'Backend', {
        prefix: 'test',
        vpc: contextVpc,
        securityGroup: contextSecurityGroup,
        privateSubnets: contextVpc.privateSubnets,
        envName: 'qa',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      const contextTemplate = Template.fromStack(contextStack);
      expect(JSON.stringify(contextTemplate.toJSON())).toContain('1.112.7');
      const parameters = contextTemplate.findParameters(
        '*',
        Match.objectLike({ Default: '/qa/renate/image-tag' }),
      );
      expect(Object.keys(parameters)).toHaveLength(0);
    });

    test('chatbotImageTag context rejects mutable values', () => {
      const contextApp = new App({ context: { chatbotImageTag: 'latest' } });
      const contextStack = new Stack(contextApp, 'MutableChatbotStack', {
        env: { account: '123456789012', region: 'eu-central-1' },
      });
      const contextVpc = new Vpc(contextStack, 'Vpc', { maxAzs: 2 });
      const contextSecurityGroup = new SecurityGroup(
        contextStack,
        'SecurityGroup',
        { vpc: contextVpc },
      );

      expect(
        () =>
          new LambdaBackend(contextStack, 'Backend', {
            prefix: 'test',
            vpc: contextVpc,
            securityGroup: contextSecurityGroup,
            privateSubnets: contextVpc.privateSubnets,
            envName: 'qa',
            ecrAccount: DEV_ECR_ACCOUNT,
          }),
      ).toThrow(/Invalid chatbotImageTag/);
    });

    test('health handler preserves cmd override', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-health-dev',
        ImageConfig: {
          Command: ['backend_orchestrator.health.lambda_handler'],
        },
      });
    });

    test('prod env image URI still references dev ECR repo (cross-account pull)', () => {
      const CROSS_ACCOUNT_ECR = '111111111111';
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'prod',
        ecrAccount: CROSS_ACCOUNT_ECR,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-prod',
        Code: {
          ImageUri: Match.objectLike({
            'Fn::Join': Match.arrayWith([
              '',
              Match.arrayWith([
                Match.stringLikeRegexp(CROSS_ACCOUNT_ECR),
                Match.stringLikeRegexp('test-chat-lambda'),
              ]),
            ]),
          }),
        },
      });
    });
  });

  describe('Chat Lambda Function', () => {
    test('should create chat handler with correct name', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        PackageType: 'Image',
      });
    });

    test('should configure default timeout and memory', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Timeout: 28,
        MemorySize: 512,
      });
    });

    test('should configure custom timeout and memory', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        timeout: 60,
        memorySize: 1024,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Timeout: 60,
        MemorySize: 1024,
      });
    });

    test('should deploy in VPC', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const chatLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-chat-dev',
        },
      });

      Object.values(chatLambdas).forEach((fn: any) => {
        expect(fn.Properties.VpcConfig).toBeDefined();
      });
    });

    test('should configure environment variables', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        logLevel: 'DEBUG',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            LOG_LEVEL: 'DEBUG',
            REGION: 'eu-central-1',
            ENVIRONMENT: 'dev',
          }),
        },
      });
    });

    test('QA manifest foundation grants selector and both retrieval slots without creating the selector', () => {
      const selector = '/qa/renate/retrieval/active-manifest';
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'qa',
        ecrAccount: DEV_ECR_ACCOUNT,
        knowledgeBaseId: 'BLUEKB1234',
        bm25IndexBucket: 'blue-processed-bucket',
        retrievalManifestParameterName: selector,
        retrievalKnowledgeBaseIds: ['GREENKB1234'],
        retrievalBm25Buckets: ['green-processed-bucket'],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-qa',
        Environment: {
          Variables: Match.objectLike({
            KNOWLEDGE_BASE_ID: 'BLUEKB1234',
            BM25_INDEX_BUCKET: 'blue-processed-bucket',
            RETRIEVAL_MANIFEST_PARAMETER: selector,
          }),
        },
      });
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith(['bedrock:Retrieve']),
              Resource: Match.arrayWith([
                'arn:aws:bedrock:eu-central-1:123456789012:knowledge-base/BLUEKB1234',
                'arn:aws:bedrock:eu-central-1:123456789012:knowledge-base/GREENKB1234',
              ]),
            }),
            Match.objectLike({
              Action: 's3:GetObject',
              Resource: Match.arrayWith([
                'arn:aws:s3:::blue-processed-bucket/bm25_index/*',
                'arn:aws:s3:::green-processed-bucket/bm25_index/releases/*',
              ]),
            }),
            Match.objectLike({
              Action: 'ssm:GetParameter',
              Resource: Match.anyValue(),
            }),
          ]),
        },
      });
      expect(JSON.stringify(template.toJSON())).toContain(
        'parameter/qa/renate/retrieval/active-manifest',
      );
      // #676: the inactive slot is granted its immutable BM25 releases and nothing
      // else — citation metadata comes from the release index, so a mutable docs/
      // sidecar would let an immutable release be described by newer data. Fix
      // missing citation titles in the metadata plumbing, not by widening this.
      expect(JSON.stringify(template.toJSON())).not.toContain(
        'arn:aws:s3:::green-processed-bucket/docs/*',
      );
      template.resourceCountIs('AWS::SSM::Parameter', 0);
    });

    test('should set CONVERSATION_TTL_DAYS to default 30', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            CONVERSATION_TTL_DAYS: '30',
          }),
        },
      });
    });

    test('should set custom CONVERSATION_TTL_DAYS when provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        conversationTtlDays: 90,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            CONVERSATION_TTL_DAYS: '90',
          }),
        },
      });
    });

    test('should enable X-Ray tracing by default', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        TracingConfig: {
          Mode: 'Active',
        },
      });
    });

    test('should disable tracing when configured', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        enableTracing: false,
      });

      template = Template.fromStack(stack);
      const chatLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-chat-dev',
        },
      });

      Object.values(chatLambdas).forEach((fn: any) => {
        expect(fn.Properties.TracingConfig).toBeUndefined();
      });
    });

    test('should use x86_64 architecture by default', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Architectures: ['x86_64'],
      });
    });

    test('should use ARM64 architecture when specified', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        architecture: lambda.Architecture.ARM_64,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Architectures: ['arm64'],
      });
    });
  });

  describe('Health Lambda Function', () => {
    test('should create health handler with correct name', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-health-dev',
        PackageType: 'Image',
      });
    });

    test('should configure health handler with smaller resources', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-health-dev',
        Timeout: 10,
        MemorySize: 256,
      });
    });

    test('should deploy health handler in VPC', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const healthLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-health-dev',
        },
      });

      Object.values(healthLambdas).forEach((fn: any) => {
        expect(fn.Properties.VpcConfig).toBeDefined();
      });
    });
  });

  describe('IAM Roles and Permissions', () => {
    test('should create Lambda execution roles', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: Match.objectLike({
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: {
                Service: 'lambda.amazonaws.com',
              },
            }),
          ]),
        }),
      });
    });

    test('should grant VPC access permissions', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith([
                'ec2:CreateNetworkInterface',
                'ec2:DescribeNetworkInterfaces',
                'ec2:DeleteNetworkInterface',
              ]),
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });

    test('should grant CloudWatch Logs permissions', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
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

      // Review functions clone this execution role; the policy must also grant
      // logging to the review log-group pattern so review Lambdas can log.
      expect(JSON.stringify(template.toJSON())).toContain(
        '/aws/lambda/test-chat-review-*:*',
      );
    });

    test('should grant Bedrock model permissions', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
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

    test('should grant DynamoDB permissions for conversation storage', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        conversationTableName: 'test-conversations',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const dynamoStatement =
        chatPolicy.Properties.PolicyDocument.Statement.find((s: any) => {
          if (Array.isArray(s.Action)) {
            return s.Action.includes('dynamodb:PutItem');
          }
          return false;
        });

      expect(dynamoStatement).toBeDefined();
      expect(dynamoStatement.Effect).toBe('Allow');
      expect(dynamoStatement.Action).toEqual([
        'dynamodb:PutItem',
        'dynamodb:UpdateItem',
        'dynamodb:Query',
        'dynamodb:GetItem',
        'dynamodb:DeleteItem',
        'dynamodb:BatchWriteItem',
      ]);
      expect(dynamoStatement.Resource).toBe(
        'arn:aws:dynamodb:eu-central-1:123456789012:table/test-conversations',
      );
    });

    test('should scope maintenance IAM permissions to chat Lambda ARN and specific KVS ARN', () => {
      const maintenanceStoreArn =
        'arn:aws:cloudfront::123456789012:key-value-store/example-kvs-id';

      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        maintenanceModeStoreArn: maintenanceStoreArn,
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;
      const statements = chatPolicy.Properties.PolicyDocument.Statement;

      const lambdaConcurrencyStatement = statements.find((s: any) => {
        const actions = Array.isArray(s.Action) ? s.Action : [s.Action];
        return actions.includes('lambda:PutFunctionConcurrency');
      });

      expect(lambdaConcurrencyStatement).toBeDefined();
      expect(lambdaConcurrencyStatement.Action).toEqual([
        'lambda:PutFunctionConcurrency',
        'lambda:DeleteFunctionConcurrency',
      ]);
      expect(lambdaConcurrencyStatement.Resource).not.toBe('*');

      const lambdaConcurrencyResource = Array.isArray(
        lambdaConcurrencyStatement.Resource,
      )
        ? lambdaConcurrencyStatement.Resource[0]
        : lambdaConcurrencyStatement.Resource;
      expect(JSON.stringify(lambdaConcurrencyResource)).toContain(
        'function:test-chat-dev',
      );

      const kvsUpdateStatement = statements.find((s: any) => {
        const actions = Array.isArray(s.Action) ? s.Action : [s.Action];
        return actions.includes('cloudfront-keyvaluestore:UpdateKeys');
      });

      expect(kvsUpdateStatement).toBeDefined();
      const kvsActions = Array.isArray(kvsUpdateStatement.Action)
        ? kvsUpdateStatement.Action
        : [kvsUpdateStatement.Action];
      expect(kvsActions).toEqual(['cloudfront-keyvaluestore:UpdateKeys']);
      expect(kvsUpdateStatement.Resource).not.toBe('*');

      const kvsResource = Array.isArray(kvsUpdateStatement.Resource)
        ? kvsUpdateStatement.Resource[0]
        : kvsUpdateStatement.Resource;
      expect(kvsResource).toBe(maintenanceStoreArn);
    });
  });

  describe('CloudWatch Logs', () => {
    test('should create log group for chat handler', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-chat-dev',
        RetentionInDays: 7,
      });
    });

    test('should create log group for health handler', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-health-dev',
        RetentionInDays: 7,
      });
    });

    test('should respect custom log retention', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        logRetentionDays: logs.RetentionDays.ONE_MONTH,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-chat-dev',
        RetentionInDays: 30,
      });
    });
  });

  describe('Resource Tagging', () => {
    test('should tag Lambda functions', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const chatLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-chat-dev',
        },
      });

      Object.values(chatLambdas).forEach((fn: any) => {
        const tags = fn.Properties.Tags || [];
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Environment).toBe('dev');
        expect(tagMap.Project).toBe('DigiBro-Chatbot');
        expect(tagMap.Component).toBe('Backend');
      });
    });

    test('should tag health Lambda with correct component', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const healthLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-health-dev',
        },
      });

      Object.values(healthLambdas).forEach((fn: any) => {
        const tags = fn.Properties.Tags || [];
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Component).toBe('HealthCheck');
      });
    });
  });

  describe('Knowledge Base Configuration', () => {
    test('should configure KB environment variables', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        knowledgeBaseId: 'test-kb-123',
        bedrockModelId: 'eu.amazon.nova-pro-v1:0',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            KNOWLEDGE_BASE_ID: 'test-kb-123',
            BEDROCK_MODEL_ID: 'eu.amazon.nova-pro-v1:0',
          }),
        },
      });
    });

    test('should grant KB retrieve permissions when knowledgeBaseId provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        knowledgeBaseId: 'test-kb-123',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const kbStatement = chatPolicy.Properties.PolicyDocument.Statement.find(
        (s: any) => {
          if (Array.isArray(s.Action)) {
            return s.Action.some(
              (action: string) =>
                action.includes('bedrock:Retrieve') ||
                action.includes('bedrock:RetrieveAndGenerate') ||
                action.includes('bedrock:GetKnowledgeBase') ||
                action.includes('bedrock:ListKnowledgeBases'),
            );
          }
          return false;
        },
      );

      expect(kbStatement).toBeDefined();
      expect(kbStatement.Effect).toBe('Allow');
      expect(kbStatement.Resource).toEqual(
        'arn:aws:bedrock:eu-central-1:123456789012:knowledge-base/test-kb-123',
      );
    });

    test('should not set KB env vars when not provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const chatLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-chat-dev',
        },
      });

      Object.values(chatLambdas).forEach((fn: any) => {
        expect(
          fn.Properties.Environment.Variables.KNOWLEDGE_BASE_ID,
        ).toBeUndefined();
      });
    });
  });

  describe('Guardrail Configuration', () => {
    test('should configure guardrail environment variables', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        guardrailId: 'test-guardrail-123',
        guardrailVersion: '1',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            BEDROCK_GUARDRAIL_ID: 'test-guardrail-123',
            BEDROCK_GUARDRAIL_VERSION: '1',
          }),
        },
      });
    });

    test('should default guardrail version to DRAFT', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        guardrailId: 'test-guardrail-123',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            BEDROCK_GUARDRAIL_ID: 'test-guardrail-123',
            BEDROCK_GUARDRAIL_VERSION: 'DRAFT',
          }),
        },
      });
    });

    test('should grant guardrail permissions when guardrailId provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        guardrailId: 'test-guardrail-123',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const guardrailStatement =
        chatPolicy.Properties.PolicyDocument.Statement.find((s: any) => {
          if (Array.isArray(s.Action)) {
            return s.Action.includes('bedrock:ApplyGuardrail');
          }
          return false;
        });

      expect(guardrailStatement).toBeDefined();
      expect(guardrailStatement.Effect).toBe('Allow');
      expect(guardrailStatement.Resource).toContain(
        'arn:aws:bedrock:eu-central-1:123456789012:guardrail/test-guardrail-123',
      );
    });

    test('should grant guardrail-profile permissions for cross-region guardrails', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        guardrailId: 'test-guardrail-123',
        guardrailProfileIdentifier: 'eu.guardrail.v1:0',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const guardrailStatement =
        chatPolicy.Properties.PolicyDocument.Statement.find((s: any) => {
          if (Array.isArray(s.Action)) {
            return s.Action.includes('bedrock:ApplyGuardrail');
          }
          return false;
        });

      expect(guardrailStatement).toBeDefined();
      expect(guardrailStatement.Resource).toEqual(
        expect.arrayContaining([
          'arn:aws:bedrock:eu-central-1:123456789012:guardrail/test-guardrail-123',
          'arn:aws:bedrock:*:123456789012:guardrail-profile/eu.guardrail.v1:0',
        ]),
      );
    });

    test('should not grant guardrail-profile permissions when not provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        guardrailId: 'test-guardrail-123',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key, _]) =>
        key.includes('ChatHandler'),
      );

      const chatPolicy = chatPolicies[0][1] as any;
      const guardrailStatement =
        chatPolicy.Properties.PolicyDocument.Statement.find((s: any) => {
          if (Array.isArray(s.Action)) {
            return s.Action.includes('bedrock:ApplyGuardrail');
          }
          return false;
        });

      expect(guardrailStatement.Resource).toBe(
        'arn:aws:bedrock:eu-central-1:123456789012:guardrail/test-guardrail-123',
      );
    });
  });

  describe('Langfuse Configuration', () => {
    test('should set Langfuse env vars when langfuseHost provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        langfuseHost: 'https://langfuse.example.com',
        langfuseSecretName: 'langfuse/dev/lambda-api-keys',
        otelIncludeContent: false,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            LANGFUSE_HOST: 'https://langfuse.example.com',
            LANGFUSE_SECRET_NAME: 'langfuse/dev/lambda-api-keys',
            OTEL_INCLUDE_CONTENT: 'false',
          }),
        },
      });
    });

    test('should set OTEL_INCLUDE_CONTENT=true when otelIncludeContent is true', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        langfuseHost: 'https://langfuse.example.com',
        otelIncludeContent: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            OTEL_INCLUDE_CONTENT: 'true',
          }),
        },
      });
    });

    describe('LANGFUSE_KEY_ROTATED_AT (#979)', () => {
      const withSecret = {
        prefix: 'test',
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        langfuseHost: 'https://langfuse.example.com',
        langfuseSecretName: 'langfuse/dev/lambda-api-keys',
      };

      test('sets the rotation marker on the chat handler, which loads the key', () => {
        new LambdaBackend(stack, 'TestLambdaBackend', {
          ...withSecret,
          vpc,
          securityGroup,
          privateSubnets: vpc.privateSubnets,
          langfuseKeyRotatedAt: '2026-11-16T22:30Z',
        });

        template = Template.fromStack(stack);
        template.hasResourceProperties('AWS::Lambda::Function', {
          FunctionName: 'test-chat-dev',
          Environment: {
            Variables: Match.objectLike({
              LANGFUSE_SECRET_NAME: 'langfuse/dev/lambda-api-keys',
              LANGFUSE_KEY_ROTATED_AT: '2026-11-16T22:30Z',
            }),
          },
        });
      });

      test('does not restart functions that never load the key (health, analytics)', () => {
        new LambdaBackend(stack, 'TestLambdaBackend', {
          ...withSecret,
          vpc,
          securityGroup,
          privateSubnets: vpc.privateSubnets,
          langfuseKeyRotatedAt: '2026-11-16T22:30Z',
        });

        template = Template.fromStack(stack);
        const fns = template.findResources('AWS::Lambda::Function');
        const withMarker = Object.values(fns)
          .filter(
            (fn: any) =>
              fn.Properties.Environment?.Variables?.LANGFUSE_KEY_ROTATED_AT,
          )
          .map((fn: any) => fn.Properties.FunctionName);
        expect(withMarker).toEqual(['test-chat-dev']);
      });

      test('a second rotation on the same day still changes the configuration', () => {
        const envOf = (rotatedAt: string) => {
          const a = new App();
          const s = new Stack(a, 'S', {
            env: { account: '123456789012', region: 'eu-central-1' },
          });
          const v = new Vpc(s, 'V', { maxAzs: 2 });
          const sg = new SecurityGroup(s, 'SG', { vpc: v });
          new LambdaBackend(s, 'B', {
            ...withSecret,
            vpc: v,
            securityGroup: sg,
            privateSubnets: v.privateSubnets,
            langfuseKeyRotatedAt: rotatedAt,
          });
          const fns = Template.fromStack(s).findResources(
            'AWS::Lambda::Function',
            { Properties: { FunctionName: 'test-chat-dev' } },
          );
          return Object.values(fns).map(
            (fn: any) => fn.Properties.Environment.Variables,
          )[0];
        };

        expect(envOf('2026-11-16T22:30Z')).not.toEqual(
          envOf('2026-11-16T23:05Z'),
        );
      });

      test('omits the marker when not configured — existing stages stay unchanged', () => {
        new LambdaBackend(stack, 'TestLambdaBackend', {
          ...withSecret,
          vpc,
          securityGroup,
          privateSubnets: vpc.privateSubnets,
        });

        template = Template.fromStack(stack);
        const fns = template.findResources('AWS::Lambda::Function');
        Object.values(fns).forEach((fn: any) => {
          expect(
            fn.Properties.Environment?.Variables?.LANGFUSE_KEY_ROTATED_AT,
          ).toBeUndefined();
        });
      });

      test.each([
        ['without a secret', { langfuseHost: 'https://langfuse.example.com' }],
        [
          'without a host (secret is set but never loaded)',
          { langfuseSecretName: 'langfuse/dev/lambda-api-keys' },
        ],
      ])('rejects a rotation marker %s', (_label, langfuse) => {
        expect(
          () =>
            new LambdaBackend(stack, 'TestLambdaBackend', {
              prefix: 'test',
              vpc,
              securityGroup,
              privateSubnets: vpc.privateSubnets,
              envName: 'dev',
              ecrAccount: DEV_ECR_ACCOUNT,
              ...langfuse,
              langfuseKeyRotatedAt: '2026-11-16T22:30Z',
            }),
        ).toThrow(
          /langfuseKeyRotatedAt requires langfuseHost and langfuseSecretName/,
        );
      });
    });

    test('should not set Langfuse env vars when langfuseHost not provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const chatLambdas = template.findResources('AWS::Lambda::Function', {
        Properties: { FunctionName: 'test-chat-dev' },
      });

      Object.values(chatLambdas).forEach((fn: any) => {
        expect(
          fn.Properties.Environment.Variables.LANGFUSE_HOST,
        ).toBeUndefined();
        expect(
          fn.Properties.Environment.Variables.LANGFUSE_SECRET_NAME,
        ).toBeUndefined();
        expect(
          fn.Properties.Environment.Variables.OTEL_INCLUDE_CONTENT,
        ).toBeUndefined();
      });
    });

    test('should grant secretsmanager:GetSecretValue when langfuseSecretName provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
        langfuseHost: 'https://langfuse.example.com',
        langfuseSecretName: 'langfuse/dev/lambda-api-keys',
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const smStatement = chatPolicy.Properties.PolicyDocument.Statement.find(
        (s: any) => s.Action === 'secretsmanager:GetSecretValue',
      );

      expect(smStatement).toBeDefined();
      expect(smStatement.Effect).toBe('Allow');
      expect(smStatement.Resource).toBe(
        'arn:aws:secretsmanager:eu-central-1:123456789012:secret:langfuse/dev/lambda-api-keys-*',
      );
    });

    test('should not grant secretsmanager permissions when langfuseSecretName not provided', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const policies = template.findResources('AWS::IAM::Policy');
      const chatPolicies = Object.entries(policies).filter(([key]) =>
        key.includes('ChatHandler'),
      );

      expect(chatPolicies.length).toBeGreaterThan(0);
      const chatPolicy = chatPolicies[0][1] as any;

      const smStatement = chatPolicy.Properties.PolicyDocument.Statement.find(
        (s: any) => s.Action === 'secretsmanager:GetSecretValue',
      );

      expect(smStatement).toBeUndefined();
    });
  });

  describe('Getter Methods', () => {
    test('should return ECR repository', () => {
      const backend = new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      const repository = backend.getChatRepository();
      expect(repository).toBeDefined();
      expect(repository.repositoryName).toBeDefined();
    });

    test('should return chat handler', () => {
      const backend = new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      const chatHandler = backend.getChatHandler();
      expect(chatHandler).toBeDefined();
      expect(chatHandler.functionName).toBeDefined();
    });

    test('should return health handler', () => {
      const backend = new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      const healthHandler = backend.getHealthHandler();
      expect(healthHandler).toBeDefined();
      expect(healthHandler.functionName).toBeDefined();
    });
  });

  describe('Outputs', () => {
    test('should export chat handler ARN', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'ARN of the chat handler Lambda function',
        Export: { Name: 'dev-ChatHandlerArn' },
      });
    });

    test('should export chat handler name', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Name of the chat handler Lambda function',
        Export: { Name: 'dev-ChatHandlerName' },
      });
    });

    test('should export health handler ARN', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'ARN of the health check Lambda function',
        Export: { Name: 'dev-HealthHandlerArn' },
      });
    });

    test('should output log group names', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'CloudWatch Log Group for chat handler',
      });

      template.hasOutput('*', {
        Description: 'CloudWatch Log Group for health handler',
      });
    });

    test('should output ECR repository URI', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'ECR Repository URI for Lambda container images',
      });
    });
  });

  describe('Consent Log Group', () => {
    test('should create consent log group with 90-day retention', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/renate/dev/consent-log',
        RetentionInDays: 90,
      });
    });

    test('should set CONSENT_LOG_GROUP environment variable on chat handler', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-chat-dev',
        Environment: {
          Variables: Match.objectLike({
            CONSENT_LOG_GROUP: '/renate/dev/consent-log',
          }),
        },
      });
    });

    test('should grant consent log group write permissions to chat role', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: ['logs:CreateLogStream', 'logs:PutLogEvents'],
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });

    test('should use DESTROY removal policy for dev env', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'dev',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const logGroups = template.findResources('AWS::Logs::LogGroup', {
        Properties: {
          LogGroupName: '/renate/dev/consent-log',
        },
      });
      const consentLg = Object.values(logGroups)[0] as any;
      expect(consentLg.DeletionPolicy).toBe('Delete');
    });

    test('should use RETAIN removal policy for prod env', () => {
      new LambdaBackend(stack, 'TestLambdaBackend', {
        prefix: 'test',
        vpc,
        securityGroup,
        privateSubnets: vpc.privateSubnets,
        envName: 'prod',
        ecrAccount: DEV_ECR_ACCOUNT,
      });

      template = Template.fromStack(stack);
      const logGroups = template.findResources('AWS::Logs::LogGroup', {
        Properties: {
          LogGroupName: '/renate/prod/consent-log',
        },
      });
      const consentLg = Object.values(logGroups)[0] as any;
      expect(consentLg.DeletionPolicy).toBe('Retain');
    });
  });
});
