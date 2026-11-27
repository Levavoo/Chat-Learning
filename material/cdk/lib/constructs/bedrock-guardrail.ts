import { Construct } from 'constructs';
import { CfnOutput, Stack } from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';

export type FilterStrength = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH';

export interface BedrockGuardrailProps {
  readonly prefix: string;
  readonly envName: string;
  readonly blockedInputMessage?: string;
  readonly blockedOutputMessage?: string;
  /** @default "HIGH" */
  readonly hateFilterStrength?: FilterStrength;
  /** @default "HIGH" */
  readonly insultsFilterStrength?: FilterStrength;
  /** @default "HIGH" */
  readonly sexualFilterStrength?: FilterStrength;
  /** @default "HIGH" */
  readonly violenceFilterStrength?: FilterStrength;
  /** @default "HIGH" */
  readonly misconductFilterStrength?: FilterStrength;
  /** Jailbreak detection. @default "HIGH" */
  readonly promptAttackFilterStrength?: FilterStrength;
  /** @default true */
  readonly enablePiiDetection?: boolean;
  readonly deniedTopics?: {
    name: string;
    definition: string;
    examples?: string[];
  }[];
  readonly blockedWords?: string[];
  /** @default true */
  readonly enableProfanityFilter?: boolean;
  /** German Sozialversicherungsnummer regex. @default true */
  readonly enableGermanSsnDetection?: boolean;
  readonly customRegexPatterns?: {
    name: string;
    description: string;
    pattern: string;
    action: 'BLOCK' | 'ANONYMIZE';
  }[];
  /** TIER_2 filters for multi-language. @default true */
  readonly enableCrossRegion?: boolean;
  /** Required for German-language support. */
  readonly crossRegionConfig?: {
    guardrailProfileIdentifier: string;
  };
}

export class BedrockGuardrail extends Construct {
  public readonly guardrail: bedrock.CfnGuardrail;
  public readonly guardrailId: string;
  public readonly guardrailArn: string;

  constructor(scope: Construct, id: string, props: BedrockGuardrailProps) {
    super(scope, id);

    const blockedInputMessage =
      props.blockedInputMessage ||
      'Ihre Nachricht enthielt nicht erlaubte Inhalte. Bitte starten sie eine neue Unterhaltung.';
    const blockedOutputMessage =
      props.blockedOutputMessage ||
      'Die Antwort enthielt nicht erlaubte Inhalte. Bitte starten sie eine neue Unterhaltung.';

    // STANDARD tier requires crossRegionConfig; profiles: {us,eu,apac}.guardrail.v1:0.
    const hasCrossRegionProfile =
      !!props.crossRegionConfig?.guardrailProfileIdentifier;

    const contentFiltersTierConfig:
      | bedrock.CfnGuardrail.ContentFiltersTierConfigProperty
      | undefined = hasCrossRegionProfile
      ? { tierName: 'STANDARD' }
      : undefined;

    const filtersConfig: bedrock.CfnGuardrail.ContentFilterConfigProperty[] = [
      {
        type: 'HATE',
        inputStrength: props.hateFilterStrength || 'HIGH',
        outputStrength: props.hateFilterStrength || 'HIGH',
      },
      {
        type: 'INSULTS',
        inputStrength: props.insultsFilterStrength || 'HIGH',
        outputStrength: props.insultsFilterStrength || 'HIGH',
      },
      {
        type: 'SEXUAL',
        inputStrength: props.sexualFilterStrength || 'HIGH',
        outputStrength: props.sexualFilterStrength || 'HIGH',
      },
      {
        type: 'VIOLENCE',
        inputStrength: props.violenceFilterStrength || 'HIGH',
        outputStrength: props.violenceFilterStrength || 'HIGH',
      },
      {
        type: 'MISCONDUCT',
        inputStrength: props.misconductFilterStrength || 'HIGH',
        outputStrength: props.misconductFilterStrength || 'HIGH',
      },
      {
        type: 'PROMPT_ATTACK',
        inputStrength: props.promptAttackFilterStrength || 'HIGH',
        outputStrength: 'NONE',
      },
    ];

    const topicsConfig: bedrock.CfnGuardrail.TopicConfigProperty[] = (
      props.deniedTopics || []
    ).map((topic) => ({
      name: topic.name,
      definition: topic.definition,
      examples: topic.examples,
      type: 'DENY',
    }));

    const hasBlockedWords = props.blockedWords && props.blockedWords.length > 0;
    const hasProfanityFilter = props.enableProfanityFilter !== false;

    const wordPolicyConfig:
      | bedrock.CfnGuardrail.WordPolicyConfigProperty
      | undefined =
      hasBlockedWords || hasProfanityFilter
        ? {
            wordsConfig: hasBlockedWords
              ? props.blockedWords!.map((word) => ({ text: word }))
              : undefined,
            managedWordListsConfig: hasProfanityFilter
              ? [{ type: 'PROFANITY' }]
              : undefined,
          }
        : undefined;

    const regexPatterns: bedrock.CfnGuardrail.RegexConfigProperty[] = [];

    // 12 chars: area(2) + birthdate(6) + initial(1) + serial(2) + check(1).
    if (props.enableGermanSsnDetection !== false) {
      regexPatterns.push({
        name: 'GermanSSN',
        description: 'German Sozialversicherungsnummer',
        pattern: '\\b[0-9]{2}[0-9]{6}[A-Za-z][0-9]{3}\\b',
        action: 'BLOCK',
      });
    }

    if (props.customRegexPatterns) {
      regexPatterns.push(
        ...props.customRegexPatterns.map((r) => ({
          name: r.name,
          description: r.description,
          pattern: r.pattern,
          action: r.action,
        })),
      );
    }

    const hasPiiEntities = props.enablePiiDetection !== false;
    const hasRegexPatterns = regexPatterns.length > 0;

    const sensitiveInfoConfig:
      | bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty
      | undefined =
      hasPiiEntities || hasRegexPatterns
        ? {
            piiEntitiesConfig: hasPiiEntities
              ? [
                  { type: 'EMAIL', action: 'NONE' },
                  { type: 'PHONE', action: 'NONE' },
                  {
                    type: 'INTERNATIONAL_BANK_ACCOUNT_NUMBER',
                    action: 'BLOCK',
                  },
                  { type: 'CREDIT_DEBIT_CARD_NUMBER', action: 'BLOCK' },
                ]
              : undefined,
            regexesConfig: hasRegexPatterns ? regexPatterns : undefined,
          }
        : undefined;

    // Profile identifier → full ARN; required for German-language support.
    const region = Stack.of(this).region;
    const account = Stack.of(this).account;
    const crossRegionConfig:
      | bedrock.CfnGuardrail.GuardrailCrossRegionConfigProperty
      | undefined = hasCrossRegionProfile
      ? {
          guardrailProfileArn: `arn:aws:bedrock:${region}:${account}:guardrail-profile/${props.crossRegionConfig!.guardrailProfileIdentifier}`,
        }
      : undefined;

    this.guardrail = new bedrock.CfnGuardrail(this, 'Guardrail', {
      name: `${props.prefix}-guardrail-${props.envName}`,
      description: `Content safety guardrail for ${props.prefix} chatbot`,
      blockedInputMessaging: blockedInputMessage,
      blockedOutputsMessaging: blockedOutputMessage,
      contentPolicyConfig: {
        filtersConfig: filtersConfig,
        contentFiltersTierConfig: contentFiltersTierConfig,
      },
      topicPolicyConfig:
        topicsConfig.length > 0
          ? {
              topicsConfig: topicsConfig,
            }
          : undefined,
      wordPolicyConfig: wordPolicyConfig,
      sensitiveInformationPolicyConfig: sensitiveInfoConfig,
      crossRegionConfig: crossRegionConfig,
    });

    this.guardrailId = this.guardrail.attrGuardrailId;
    this.guardrailArn = this.guardrail.attrGuardrailArn;

    new CfnOutput(this, 'GuardrailId', {
      value: this.guardrail.attrGuardrailId,
      description: 'Bedrock Guardrail ID',
      exportName: `${props.envName}-GuardrailId`,
    });

    new CfnOutput(this, 'GuardrailArn', {
      value: this.guardrail.attrGuardrailArn,
      description: 'Bedrock Guardrail ARN',
      exportName: `${props.envName}-GuardrailArn`,
    });

    // Intentionally no CfnGuardrailVersion — DRAFT always serves latest.
    new CfnOutput(this, 'GuardrailVersionOutput', {
      value: 'DRAFT',
      description: 'Bedrock Guardrail Version (where DRAFT = always latest)',
      exportName: `${props.envName}-GuardrailVersion`,
    });
  }

  getGuardrailId(): string {
    return this.guardrail.attrGuardrailId;
  }

  /** Always "DRAFT" so queries pick up config changes immediately. */
  getGuardrailVersion(): string {
    return 'DRAFT';
  }

  getGuardrailArn(): string {
    return this.guardrail.attrGuardrailArn;
  }
}
