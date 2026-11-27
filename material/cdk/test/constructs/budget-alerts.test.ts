import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as sns from 'aws-cdk-lib/aws-sns';
import { BudgetAlerts } from '../../lib/constructs/monitoring/budget-alerts';

describe('BudgetAlerts', () => {
  let stack: cdk.Stack;
  let alertTopic: sns.Topic;

  beforeEach(() => {
    const app = new cdk.App();
    stack = new cdk.Stack(app, 'TestStack');
    alertTopic = new sns.Topic(stack, 'AlertTopic', {
      topicName: 'test-alerts',
    });
  });

  it('creates a monthly cost budget with correct limit', () => {
    new BudgetAlerts(stack, 'Budget', {
      prefix: 'renate',
      envName: 'prod',
      monthlyBudgetUsd: 7000,
      thresholds: [
        { percentage: 50, notificationType: 'FORECASTED' },
        { percentage: 70, notificationType: 'ACTUAL' },
        { percentage: 100, notificationType: 'ACTUAL' },
      ],
      alertTopic,
    });

    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Budgets::Budget', {
      Budget: {
        BudgetName: 'renate-monthly-cost-prod',
        BudgetType: 'COST',
        TimeUnit: 'MONTHLY',
        BudgetLimit: {
          Amount: 7000,
          Unit: 'USD',
        },
      },
    });
  });

  it('creates notifications for all three thresholds with SNS subscriber', () => {
    new BudgetAlerts(stack, 'Budget', {
      prefix: 'renate',
      envName: 'prod',
      monthlyBudgetUsd: 7000,
      thresholds: [
        { percentage: 50, notificationType: 'FORECASTED' },
        { percentage: 70, notificationType: 'ACTUAL' },
        { percentage: 100, notificationType: 'ACTUAL' },
      ],
      alertTopic,
    });

    const template = Template.fromStack(stack);

    template.hasResourceProperties('AWS::Budgets::Budget', {
      NotificationsWithSubscribers: Match.arrayWith([
        Match.objectLike({
          Notification: {
            ComparisonOperator: 'GREATER_THAN',
            NotificationType: 'FORECASTED',
            Threshold: 50,
            ThresholdType: 'PERCENTAGE',
          },
          Subscribers: Match.arrayWith([
            Match.objectLike({ SubscriptionType: 'SNS' }),
          ]),
        }),
        Match.objectLike({
          Notification: {
            ComparisonOperator: 'GREATER_THAN',
            NotificationType: 'ACTUAL',
            Threshold: 70,
            ThresholdType: 'PERCENTAGE',
          },
        }),
        Match.objectLike({
          Notification: {
            ComparisonOperator: 'GREATER_THAN',
            NotificationType: 'ACTUAL',
            Threshold: 100,
            ThresholdType: 'PERCENTAGE',
          },
        }),
      ]),
    });
  });

  it('creates exactly one budget resource', () => {
    new BudgetAlerts(stack, 'Budget', {
      prefix: 'renate',
      envName: 'prod',
      monthlyBudgetUsd: 7000,
      thresholds: [{ percentage: 100, notificationType: 'ACTUAL' }],
      alertTopic,
    });

    const template = Template.fromStack(stack);
    template.resourceCountIs('AWS::Budgets::Budget', 1);
  });

  it('is not created for non-prod environments when config is absent', () => {
    const template = Template.fromStack(stack);
    template.resourceCountIs('AWS::Budgets::Budget', 0);
  });
});
