import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { BedrockGuardrail } from '../../lib/constructs/bedrock-guardrail';

describe('BedrockGuardrail Construct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
  });

  describe('Guardrail Creation', () => {
    test('should create guardrail with default configuration', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        Name: 'test-guardrail-dev',
      });
    });

    test('should create guardrail with all content filters at HIGH strength', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        ContentPolicyConfig: {
          FiltersConfig: Match.arrayWith([
            Match.objectLike({
              Type: 'HATE',
              InputStrength: 'HIGH',
              OutputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'INSULTS',
              InputStrength: 'HIGH',
              OutputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'SEXUAL',
              InputStrength: 'HIGH',
              OutputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'VIOLENCE',
              InputStrength: 'HIGH',
              OutputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'MISCONDUCT',
              InputStrength: 'HIGH',
              OutputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'PROMPT_ATTACK',
              InputStrength: 'HIGH',
              OutputStrength: 'NONE',
            }),
          ]),
        },
      });
    });

    test('should set custom blocked messages', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        blockedInputMessage: 'Custom input blocked message',
        blockedOutputMessage: 'Custom output blocked message',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        BlockedInputMessaging: 'Custom input blocked message',
        BlockedOutputsMessaging: 'Custom output blocked message',
      });
    });

    test('should enable PII detection by default', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: {
          PiiEntitiesConfig: Match.arrayWith([
            Match.objectLike({ Type: 'EMAIL', Action: 'NONE' }),
            Match.objectLike({ Type: 'PHONE', Action: 'NONE' }),
            Match.objectLike({
              Type: 'CREDIT_DEBIT_CARD_NUMBER',
              Action: 'BLOCK',
            }),
          ]),
        },
      });
    });

    test('should enable profanity filter by default', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        WordPolicyConfig: {
          ManagedWordListsConfig: [{ Type: 'PROFANITY' }],
        },
      });
    });

    test('should add denied topics when provided', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        deniedTopics: [
          {
            name: 'CompetitorInfo',
            definition: 'Information about competitor products',
            examples: ['Tell me about competitor X'],
          },
        ],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        TopicPolicyConfig: {
          TopicsConfig: [
            {
              Name: 'CompetitorInfo',
              Definition: 'Information about competitor products',
              Examples: ['Tell me about competitor X'],
              Type: 'DENY',
            },
          ],
        },
      });
    });

    test('should add blocked words when provided', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        blockedWords: ['badword1', 'badword2'],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        WordPolicyConfig: {
          WordsConfig: [{ Text: 'badword1' }, { Text: 'badword2' }],
        },
      });
    });

    test('should enable German SSN detection by default', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: {
          RegexesConfig: Match.arrayWith([
            Match.objectLike({
              Name: 'GermanSSN',
              Description: 'German Sozialversicherungsnummer',
              Pattern: '\\b[0-9]{2}[0-9]{6}[A-Za-z][0-9]{3}\\b',
              Action: 'BLOCK',
            }),
          ]),
        },
      });
    });

    test('should support custom regex patterns', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        customRegexPatterns: [
          {
            name: 'CustomPattern',
            description: 'Test pattern',
            pattern: 'TEST-[0-9]+',
            action: 'ANONYMIZE',
          },
        ],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: {
          RegexesConfig: Match.arrayWith([
            Match.objectLike({
              Name: 'CustomPattern',
              Action: 'ANONYMIZE',
            }),
          ]),
        },
      });
    });

    test('should use custom filter strengths', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        hateFilterStrength: 'MEDIUM',
        violenceFilterStrength: 'LOW',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        ContentPolicyConfig: {
          FiltersConfig: Match.arrayWith([
            Match.objectLike({
              Type: 'HATE',
              InputStrength: 'MEDIUM',
              OutputStrength: 'MEDIUM',
            }),
            Match.objectLike({
              Type: 'VIOLENCE',
              InputStrength: 'LOW',
              OutputStrength: 'LOW',
            }),
          ]),
        },
      });
    });
  });

  describe('Outputs', () => {
    test('should export guardrail ID, ARN, and version', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      const outputs = template.toJSON().Outputs || {};
      const outputKeys = Object.keys(outputs);

      // Verify all expected exports exist
      const exportNames = outputKeys.map((key) => outputs[key].Export?.Name);
      expect(exportNames).toContain('dev-GuardrailId');
      expect(exportNames).toContain('dev-GuardrailArn');
      expect(exportNames).toContain('dev-GuardrailVersion');
    });
  });

  describe('German Content Blocking', () => {
    test('should use German blocked messages by default', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        BlockedInputMessaging:
          'Ihre Nachricht enthielt nicht erlaubte Inhalte. Bitte starten sie eine neue Unterhaltung.',
        BlockedOutputsMessaging:
          'Die Antwort enthielt nicht erlaubte Inhalte. Bitte starten sie eine neue Unterhaltung.',
      });
    });

    test('should enable STANDARD tier with cross-region config for German language support', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        crossRegionConfig: {
          guardrailProfileIdentifier: 'eu.guardrail.v1:0',
        },
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        ContentPolicyConfig: {
          ContentFiltersTierConfig: {
            TierName: 'STANDARD',
          },
        },
        CrossRegionConfig: {
          GuardrailProfileArn:
            'arn:aws:bedrock:eu-central-1:123456789012:guardrail-profile/eu.guardrail.v1:0',
        },
      });
    });

    test('should not set tier config without cross-region config', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        ContentPolicyConfig: {
          ContentFiltersTierConfig: Match.absent(),
        },
        CrossRegionConfig: Match.absent(),
      });
    });

    test('should allow disabling German SSN detection', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        enableGermanSsnDetection: false,
        enablePiiDetection: false,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: Match.absent(),
      });
    });

    test('should combine German SSN detection with custom regex patterns', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        customRegexPatterns: [
          {
            name: 'GermanTaxId',
            description: 'German Steueridentifikationsnummer',
            pattern: '\\b[0-9]{11}\\b',
            action: 'BLOCK',
          },
        ],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: {
          RegexesConfig: Match.arrayWith([
            Match.objectLike({
              Name: 'GermanSSN',
              Action: 'BLOCK',
            }),
            Match.objectLike({
              Name: 'GermanTaxId',
              Description: 'German Steueridentifikationsnummer',
              Action: 'BLOCK',
            }),
          ]),
        },
      });
    });

    test('should detect German IBAN with PII detection', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        enablePiiDetection: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        SensitiveInformationPolicyConfig: {
          PiiEntitiesConfig: Match.arrayWith([
            {
              Type: 'INTERNATIONAL_BANK_ACCOUNT_NUMBER',
              Action: 'BLOCK',
            },
          ]),
        },
      });
    });

    test('should configure full German guardrail with all filters', () => {
      new BedrockGuardrail(stack, 'TestGuardrail', {
        prefix: 'test',
        envName: 'dev',
        crossRegionConfig: {
          guardrailProfileIdentifier: 'eu.guardrail.v1:0',
        },
        blockedWords: ['Schimpfwort', 'Beleidigung'],
        deniedTopics: [
          {
            name: 'VerboteneThemen',
            definition: 'Themen die nicht besprochen werden dürfen',
            examples: ['Beispiel verbotenes Thema'],
          },
        ],
        hateFilterStrength: 'HIGH',
        insultsFilterStrength: 'HIGH',
        violenceFilterStrength: 'HIGH',
        enablePiiDetection: true,
        enableGermanSsnDetection: true,
        enableProfanityFilter: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Bedrock::Guardrail', {
        ContentPolicyConfig: {
          FiltersConfig: Match.arrayWith([
            Match.objectLike({
              Type: 'HATE',
              InputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'INSULTS',
              InputStrength: 'HIGH',
            }),
            Match.objectLike({
              Type: 'VIOLENCE',
              InputStrength: 'HIGH',
            }),
          ]),
          ContentFiltersTierConfig: {
            TierName: 'STANDARD',
          },
        },
        WordPolicyConfig: {
          WordsConfig: Match.arrayWith([
            { Text: 'Schimpfwort' },
            { Text: 'Beleidigung' },
          ]),
          ManagedWordListsConfig: [{ Type: 'PROFANITY' }],
        },
        TopicPolicyConfig: {
          TopicsConfig: Match.arrayWith([
            Match.objectLike({
              Name: 'VerboteneThemen',
              Type: 'DENY',
            }),
          ]),
        },
        SensitiveInformationPolicyConfig: {
          PiiEntitiesConfig: Match.arrayWith([
            Match.objectLike({ Type: 'INTERNATIONAL_BANK_ACCOUNT_NUMBER' }),
          ]),
          RegexesConfig: Match.arrayWith([
            Match.objectLike({ Name: 'GermanSSN' }),
          ]),
        },
        CrossRegionConfig: {
          GuardrailProfileArn:
            'arn:aws:bedrock:eu-central-1:123456789012:guardrail-profile/eu.guardrail.v1:0',
        },
      });
    });
  });
});
