import { App, Stack } from 'aws-cdk-lib';
import { SecurityGroup, Vpc } from 'aws-cdk-lib/aws-ec2';

import { chatbotParametersMap } from '../../parameter';
import { LambdaBackend } from '../../lib/constructs/lambda-backend';
import { getChatbotParameters } from '../../lib/utils/parameter-models';

const DEV_LANGFUSE_HOST = 'https://langfuse-renate-dev.kilab-platform.de';
const PROD_LANGFUSE_HOST = 'https://langfuse.renate-observability.de';
const TEST_ECR_ACCOUNT = '123456789012';

function createBackend(
  envName: string,
  langfuseHost?: string,
  langfuseSecretName?: string,
  otelIncludeContent?: boolean,
): void {
  const app = new App();
  const stack = new Stack(app, 'TestStack', {
    env: { account: TEST_ECR_ACCOUNT, region: 'eu-central-1' },
  });
  const vpc = new Vpc(stack, 'Vpc', { maxAzs: 2 });
  const securityGroup = new SecurityGroup(stack, 'SecurityGroup', { vpc });

  new LambdaBackend(stack, 'Backend', {
    prefix: 'test',
    vpc,
    securityGroup,
    privateSubnets: vpc.privateSubnets,
    envName,
    ecrAccount: TEST_ECR_ACCOUNT,
    langfuseHost,
    langfuseSecretName,
    otelIncludeContent,
  });
}

describe('LangFuse endpoint isolation', () => {
  test.each([
    ['dev', 'langfuse/dev/lambda-api-keys'],
    ['qa', 'langfuse/qa/lambda-api-keys'],
    ['preprod', 'langfuse/preprod/lambda-api-keys'],
  ] as const)(
    '%s uses the shared non-Prod endpoint with its own credential path',
    (envName, secretName) => {
      const parameters = getChatbotParameters(
        new App(),
        envName,
        chatbotParametersMap,
      );

      expect(parameters.langfuseHost).toBe(DEV_LANGFUSE_HOST);
      expect(parameters.langfuseSecretName).toBe(secretName);
      // #774: content export is explicitly approved by default in every
      // stage until this default is deliberately withdrawn.
      expect(parameters.otelIncludeContent).toBe(true);
    },
  );

  test('uses the #773 transitional shared endpoint until the dedicated Prod instance is live', () => {
    const parameters = getChatbotParameters(
      new App(),
      'prod',
      chatbotParametersMap,
    );

    expect(parameters.langfuseHost).toBe(DEV_LANGFUSE_HOST);
    expect(parameters.langfuseSecretName).toBe('langfuse/prod/lambda-api-keys');
    // #774: content export is explicitly approved by default in every
    // stage, including Prod, until this default is deliberately withdrawn.
    expect(parameters.otelIncludeContent).toBe(true);
  });

  test('allows the #773 transitional Dev LangFuse endpoint in a Prod Lambda', () => {
    expect(() =>
      createBackend(
        'prod',
        DEV_LANGFUSE_HOST,
        'langfuse/prod/lambda-api-keys',
        false,
      ),
    ).not.toThrow();
  });

  test('rejects an unapproved third-party LangFuse endpoint in a Prod Lambda', () => {
    expect(() =>
      createBackend(
        'prod',
        'https://langfuse.example.invalid',
        'test-prod-secret-reference',
        false,
      ),
    ).toThrow('Prod LangFuse must use its dedicated endpoint');
  });

  test('#774: allows content export with the designated Prod endpoint by default', () => {
    expect(() =>
      createBackend(
        'prod',
        PROD_LANGFUSE_HOST,
        'test-prod-secret-reference',
        true,
      ),
    ).not.toThrow();
  });

  test('rejects the Prod endpoint outside Prod', () => {
    expect(() =>
      createBackend(
        'preprod',
        PROD_LANGFUSE_HOST,
        'test-prod-secret-reference',
        false,
      ),
    ).toThrow(
      'Only the prod deployment may reference the dedicated Prod LangFuse endpoint',
    );
  });

  test('allows the designated Prod route regardless of content-export setting', () => {
    expect(() =>
      createBackend(
        'prod',
        PROD_LANGFUSE_HOST,
        'test-prod-secret-reference',
        false,
      ),
    ).not.toThrow();
  });
});
