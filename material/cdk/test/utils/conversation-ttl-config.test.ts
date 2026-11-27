import * as cdk from 'aws-cdk-lib';

import { chatbotParametersMap } from '../../parameter';
import { getChatbotParameters } from '../../lib/utils/parameter-models';

describe('chatbotParametersMap — conversation TTL', () => {
  test.each(['dev', 'qa', 'preprod', 'prod'] as const)(
    'configures %s for the DSFA retention period of 180 days',
    (envName) => {
      const params = getChatbotParameters(
        new cdk.App(),
        envName,
        chatbotParametersMap,
      );

      expect(params.conversationTtlDays).toBe(180);
    },
  );

  test('keeps the demo environment on the schema default', () => {
    const params = getChatbotParameters(
      new cdk.App(),
      'demo',
      chatbotParametersMap,
    );

    expect(params.conversationTtlDays).toBe(30);
  });
});
