import * as cdk from 'aws-cdk-lib';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';

export interface AlertingTopicProps {
  /** Resource name prefix */
  readonly prefix: string;
  /** Environment name */
  readonly envName: string;
  /** Single email address for alarm notifications (legacy, prefer alertEmails) */
  readonly alertEmail?: string;
  /** List of email addresses for alarm notifications */
  readonly alertEmails?: string[];
}

/**
 * SNS Topic for CloudWatch alarm notifications with email subscription support.
 */
export class AlertingTopic extends Construct {
  public readonly topic: sns.Topic;

  constructor(scope: Construct, id: string, props: AlertingTopicProps) {
    super(scope, id);

    const { prefix, envName, alertEmail, alertEmails } = props;

    this.topic = new sns.Topic(this, 'AlertTopic', {
      topicName: `${prefix}-alerts-${envName}`,
      displayName: `${prefix} Monitoring Alerts (${envName})`,
    });

    const emails = [
      ...(alertEmails ?? []),
      ...(alertEmail ? [alertEmail] : []),
    ].filter((v, i, a) => a.indexOf(v) === i);

    for (const email of emails) {
      this.topic.addSubscription(new subscriptions.EmailSubscription(email));
    }

    new cdk.CfnOutput(this, 'AlertTopicArn', {
      value: this.topic.topicArn,
      description: 'SNS Topic ARN for monitoring alerts',
      exportName: `${prefix}-${envName}-AlertTopicArn`,
    });
  }
}
