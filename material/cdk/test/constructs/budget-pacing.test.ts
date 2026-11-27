import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { BudgetPacing } from '../../lib/constructs/monitoring/budget-pacing';

const KVS_ARN =
  'arn:aws:cloudfront::123456789012:key-value-store/abcdef01-2345-6789-abcd-ef0123456789';

describe('BudgetPacing', () => {
  let stack: cdk.Stack;
  let alertTopic: sns.Topic;
  let chatHandler: lambda.Function;
  let reasonParam: ssm.StringParameter;

  beforeEach(() => {
    const app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
    alertTopic = new sns.Topic(stack, 'AlertTopic');
    chatHandler = new lambda.Function(stack, 'ChatHandler', {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'index.handler',
      code: lambda.Code.fromInline('def handler(e, c): pass'),
    });
    reasonParam = new ssm.StringParameter(stack, 'ReasonParam', {
      parameterName: '/dev/renate/maintenance-reason',
      stringValue: 'none',
    });
  });

  function subject(overrides: Record<string, unknown> = {}) {
    return new BudgetPacing(stack, 'Pacing', {
      prefix: 'renate',
      envName: 'dev',
      monthlyBudgetUsd: 7000,
      maintenanceKvsArn: KVS_ARN,
      chatHandler,
      alertTopic,
      maintenanceReasonParameter: reasonParam,
      distributionId: 'EDFDVBD6EXAMPLE',
      ...overrides,
    });
  }

  it('creates a Python Lambda that is not VPC-attached', () => {
    subject();
    const template = Template.fromStack(stack);

    // A cost-control Lambda behind a NAT Gateway would add cost for nothing.
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'renate-budget-pacing-dev',
      Runtime: 'python3.13',
      Handler: 'handler.lambda_handler',
      Timeout: 30,
      VpcConfig: Match.absent(),
    });
  });

  it('schedules twice-daily evaluation at 06:00 and 12:00 UTC', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Events::Rule', {
      ScheduleExpression: 'cron(0 6,8,10,12,14,16,18,20 * * ? *)',
      State: 'ENABLED',
    });
  });

  it('passes budget and target resources as environment variables', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          ENV_NAME: 'dev',
          MONTHLY_BUDGET_USD: '7000',
          KVS_ARN: KVS_ARN,
          DISTRIBUTION_ID: Match.anyValue(),
          MAINTENANCE_REASON_PARAM: Match.anyValue(),
          CHAT_HANDLER_NAME: Match.anyValue(),
          SNS_TOPIC_ARN: Match.anyValue(),
        }),
      },
    });
  });

  it('grants Cost Explorer read with the AWS-required wildcard', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: 'ReadCostExplorer',
            Action: 'ce:GetCostAndUsage',
            Effect: 'Allow',
            Resource: '*',
          }),
        ]),
      },
    });
  });

  it('grants all three KVS actions scoped to the maintenance store', () => {
    subject();
    const template = Template.fromStack(stack);

    // GetKey is the grant that gets forgotten (dev incident 2026-07-21).
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: 'ToggleMaintenanceFlag',
            Effect: 'Allow',
            Action: [
              'cloudfront-keyvaluestore:DescribeKeyValueStore',
              'cloudfront-keyvaluestore:UpdateKeys',
              'cloudfront-keyvaluestore:GetKey',
            ],
            Resource: KVS_ARN,
          }),
        ]),
      },
    });
  });

  it('grants concurrency control scoped to the chat handler', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: 'ThrottleChatHandler',
            Effect: 'Allow',
            Action: [
              'lambda:PutFunctionConcurrency',
              'lambda:DeleteFunctionConcurrency',
            ],
          }),
        ]),
      },
    });
  });

  it('grants CloudFront cache invalidation scoped to the distribution', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Sid: 'InvalidateCloudFrontCache',
            Effect: 'Allow',
            Action: 'cloudfront:CreateInvalidation',
            Resource: Match.stringLikeRegexp(
              'arn:aws:cloudfront::123456789012:distribution/EDFDVBD6EXAMPLE',
            ),
          }),
        ]),
      },
    });
  });

  it('creates an error alarm wired to the alert topic', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: 'renate-budget-pacing-errors-dev',
      MetricName: 'Errors',
      Threshold: 1,
      ComparisonOperator: 'GreaterThanOrEqualToThreshold',
      TreatMissingData: 'notBreaching',
      AlarmActions: Match.anyValue(),
    });
  });

  it('references the runbook in the alarm description', () => {
    subject();
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmDescription: Match.stringLikeRegexp('runbooks/budget_pacing'),
    });
  });

  it('honours a custom monthly budget', () => {
    subject({ monthlyBudgetUsd: 50 });
    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({ MONTHLY_BUDGET_USD: '50' }),
      },
    });
  });
});
