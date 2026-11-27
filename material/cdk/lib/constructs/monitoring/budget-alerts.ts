import * as cdk from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as sns from 'aws-cdk-lib/aws-sns';
import { Construct } from 'constructs';

export interface BudgetThreshold {
  /** Percentage threshold (e.g. 50, 70, 100) */
  readonly percentage: number;
  /** Notification type: ACTUAL or FORECASTED */
  readonly notificationType: 'ACTUAL' | 'FORECASTED';
}

export interface BudgetAlertsProps {
  /** Resource name prefix */
  readonly prefix: string;
  /** Environment name */
  readonly envName: string;
  /** Monthly budget limit in USD (AWS reports pre-discount, incl. tax) */
  readonly monthlyBudgetUsd: number;
  /** Budget thresholds to alert on */
  readonly thresholds: BudgetThreshold[];
  /** SNS topic for notifications */
  readonly alertTopic: sns.ITopic;
}

/**
 * AWS Budget with SNS notifications at configurable thresholds.
 *
 * Designed for the Renate production account:
 * - Fixed annual budget of 60.000 € brutto (5.000 €/month inkl. MwSt)
 * - AWS Budgets sees costs in USD, pre-discount, incl. US tax
 * - Conversion: 5.000€ / 1.19 MwSt / 0.725 discount * 1.14 FX * 1.154 tax ≈ $7.048
 * - Budget set to $7.000 (rounded down for safety margin)
 * - Alerts at 50 % (forecasted), 70 % (actual), 100 % (actual)
 * - CostTypes: IncludeDiscount=false, IncludeTax=true (matches existing account budgets)
 *
 * Note: AWS Budgets has 8–24h delay. For real-time cost control,
 * use Budget Pacing (#579) which reads Cost Explorer directly.
 */
export class BudgetAlerts extends Construct {
  public readonly budget: budgets.CfnBudget;

  constructor(scope: Construct, id: string, props: BudgetAlertsProps) {
    super(scope, id);

    const { prefix, envName, monthlyBudgetUsd, thresholds, alertTopic } = props;

    // AWS Budgets service needs permission to publish to the SNS topic
    alertTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'AllowBudgetsPublish',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('budgets.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [alertTopic.topicArn],
        conditions: {
          StringEquals: {
            'aws:SourceAccount': cdk.Stack.of(this).account,
          },
        },
      }),
    );

    const notifications = thresholds.map((t) => ({
      notification: {
        comparisonOperator: 'GREATER_THAN',
        notificationType: t.notificationType,
        threshold: t.percentage,
        thresholdType: 'PERCENTAGE',
      },
      subscribers: [
        {
          subscriptionType: 'SNS',
          address: alertTopic.topicArn,
        },
      ],
    }));

    this.budget = new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: `${prefix}-monthly-cost-${envName}`,
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: {
          amount: monthlyBudgetUsd,
          unit: 'USD',
        },
        costTypes: {
          includeDiscount: false,
          includeTax: true,
          includeSubscription: true,
          includeRefund: false,
          includeCredit: false,
          includeUpfront: true,
          includeRecurring: true,
          includeOtherSubscription: true,
          includeSupport: true,
          useBlended: false,
          useAmortized: false,
        },
      },
      notificationsWithSubscribers: notifications,
    });

    new cdk.CfnOutput(this, 'BudgetName', {
      value: `${prefix}-monthly-cost-${envName}`,
      description: 'AWS Budget name for cost monitoring',
    });
  }
}
