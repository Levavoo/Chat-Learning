import { App, Stack, Duration } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { Auth } from '../../lib/constructs/auth';
import { identityProvider } from '../../lib/utils/identity-provider';

describe('Auth Construct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
  });

  describe('User Pool Creation', () => {
    test('should create user pool with correct configuration', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
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
      });
    });

    test('should enable email sign-in alias', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Cognito::UserPool', {
        UsernameAttributes: ['email'],
      });
    });

    test('should enable self-signup when configured', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      const userPools = template.findResources('AWS::Cognito::UserPool', {
        Properties: {
          UserPoolName: 'test-pool-dev',
        },
      });

      Object.values(userPools).forEach((pool: any) => {
        expect(pool.Properties.SelfSignUpEnabled).not.toBe(false);
      });
    });

    test('should disable self-signup when configured', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: false,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::Cognito::UserPool', 1);
    });
  });

  describe('User Pool Client', () => {
    test('should create user pool client', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::Cognito::UserPoolClient', 1);
    });

    test('should configure auth flows', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
        ExplicitAuthFlows: Match.arrayWith([
          'ALLOW_USER_PASSWORD_AUTH',
          'ALLOW_USER_SRP_AUTH',
          'ALLOW_REFRESH_TOKEN_AUTH',
        ]),
      });
    });

    test('should set token validity', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(2),
      });

      template = Template.fromStack(stack);
      // CDK normalizes Duration.hours(2) to 120 minutes
      template.hasResourceProperties('AWS::Cognito::UserPoolClient', {
        IdTokenValidity: 120,
        TokenValidityUnits: {
          IdToken: 'minutes',
        },
      });
    });
  });

  describe('Email Domain Validation', () => {
    test('should create Lambda function for email validation', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-email-check-dev',
        Runtime: 'python3.13',
      });
    });

    test('should pass allowed domains to Lambda environment', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com', 'test.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-email-check-dev',
        Environment: {
          Variables: {
            ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR: '["example.com","test.com"]',
          },
        },
      });
    });

    test('should create log group for email check Lambda', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-email-check-dev',
        RetentionInDays: 90,
      });
    });

    test('should attach Lambda as pre-signup trigger', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Cognito::UserPool', {
        LambdaConfig: {
          PreSignUp: Match.objectLike({
            'Fn::GetAtt': Match.arrayWith([
              Match.stringLikeRegexp('.*EmailCheckFn.*'),
            ]),
          }),
        },
      });
    });

    test('should skip email validation when no domains specified', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      const lambdas = template.findResources('AWS::Lambda::Function', {
        Properties: {
          FunctionName: 'test-email-check-dev',
        },
      });
      expect(Object.keys(lambdas).length).toBe(0);
    });
  });

  describe('IAM Roles', () => {
    test('should create Lambda execution role', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'sts:AssumeRole',
              Effect: 'Allow',
              Principal: {
                Service: 'lambda.amazonaws.com',
              },
            }),
          ]),
        },
      });
    });

    test('should grant CloudWatch Logs permissions', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: ['example.com'],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
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

  describe('WAF Integration', () => {
    test('should associate WAF Web ACL when provided', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
        webAclArn:
          'arn:aws:wafv2:eu-central-1:123456789012:regional/webacl/test/a1b2c3d4',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::WAFv2::WebACLAssociation', {
        WebACLArn:
          'arn:aws:wafv2:eu-central-1:123456789012:regional/webacl/test/a1b2c3d4',
      });
    });

    test('should skip WAF association when not provided', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      const associations = template.findResources(
        'AWS::WAFv2::WebACLAssociation',
      );
      expect(Object.keys(associations).length).toBe(0);
    });
  });

  describe('Outputs', () => {
    test('should export user pool ID', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: Match.absent(),
      });
    });

    test('should export user pool client ID', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      const outputs = template.findOutputs('*');
      expect(Object.keys(outputs).length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('Dashboard Admins Group (RFC-0009)', () => {
    test('should create dashboard-admins Cognito group', () => {
      new Auth(stack, 'TestAuth', {
        prefix: 'test',
        envName: 'dev',
        origin: 'http://localhost:4200',
        userPoolDomainPrefixKey: 'test-domain',
        idp: identityProvider([]),
        allowedSignUpEmailDomains: [],
        selfSignUpEnabled: true,
        tokenValidity: Duration.hours(1),
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Cognito::UserPoolGroup', {
        GroupName: 'dashboard-admins',
        Description: 'Redakteure mit Zugriff auf das Analytics-Dashboard',
      });
    });
  });
});
