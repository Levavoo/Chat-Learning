import { App, Stack } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';

import { ConversationTable } from '../../lib/constructs/dynamodb';

describe('ConversationTable', () => {
  const synth = () => {
    const app = new App();
    const stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
    new ConversationTable(stack, 'ConversationTable', {
      prefix: 'renate',
      envName: 'dev',
    });
    return Template.fromStack(stack);
  };

  // TKT-REV-09: TTL lets review-environment items auto-expire after teardown.
  test('enables TTL on the ttl attribute', () => {
    const template = synth();

    template.hasResourceProperties('AWS::DynamoDB::GlobalTable', {
      TimeToLiveSpecification: {
        AttributeName: 'ttl',
        Enabled: true,
      },
    });
  });

  test('keeps the expected key schema', () => {
    const template = synth();

    template.hasResourceProperties('AWS::DynamoDB::GlobalTable', {
      TableName: 'renate-conversations-dev',
      KeySchema: [
        { AttributeName: 'session_id', KeyType: 'HASH' },
        { AttributeName: 'message_id', KeyType: 'RANGE' },
      ],
    });
  });

  test('has domain-created_at-index GSI for analytics queries (RFC-0009)', () => {
    const template = synth();

    template.hasResourceProperties('AWS::DynamoDB::GlobalTable', {
      GlobalSecondaryIndexes: [
        {
          IndexName: 'domain-created_at-index',
          KeySchema: [
            { AttributeName: 'domain', KeyType: 'HASH' },
            { AttributeName: 'created_at', KeyType: 'RANGE' },
          ],
          Projection: { ProjectionType: 'ALL' },
        },
      ],
    });
  });
});
