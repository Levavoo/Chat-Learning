import { StackProps } from 'aws-cdk-lib';
import * as logs from 'aws-cdk-lib/aws-logs';
import {
  WafManagedRuleActions,
  WafRuleCountOverrides,
} from './waf-managed-rules';

export const PROD_ENV_NAMES = ['prod', 'production'] as const;

export function isProdEnv(envName: string): boolean {
  return PROD_ENV_NAMES.includes(envName as (typeof PROD_ENV_NAMES)[number]);
}

export interface NetworkConfig {
  /** @default 10.0.0.0/16 */
  readonly vpcCidr?: string;
  /** @default 2 */
  readonly maxAzs?: number;
  /** @default 1 */
  readonly natGateways?: number;
}

export interface AuthConfig {
  /** Globally unique User Pool domain prefix. */
  readonly userPoolDomainPrefix: string;
  /** @default [] */
  readonly allowedSignUpEmailDomains?: string[];
  /** @default true */
  readonly selfSignUpEnabled?: boolean;
  /** @default 60 */
  readonly tokenValidityMinutes?: number;
  /** Skips Cognito authorizer when true. @default false */
  readonly anonymousAccess?: boolean;
  /** Internal DRV-employee mode. @default false */
  readonly intern?: boolean;
}

export interface FrontendConfig {
  /** Extra CORS origin — primary origin is derived from CloudFront at runtime. */
  readonly origin?: string;
  readonly domainName?: string;
  readonly hostedZoneId?: string;
  /** Required for delegated subdomains and ccTLDs where the zone is not the immediate parent. */
  readonly hostedZoneName?: string;
  /** Pre-existing ACM cert ARN (must be us-east-1 for CloudFront). Replaces the auto-created DNS-validated cert. */
  readonly certificateArn?: string;
  /**
   * Pre-cutover DNS-only preparation: creates A/AAAA alias records to the
   * distribution WITHOUT attaching the domain to CloudFront or requiring a cert.
   */
  readonly dnsRecordName?: string;
  /** @default true */
  readonly enableIpV6?: boolean;
  readonly webAclId?: string;
  /** ISO 3166-1 alpha-2 codes allowed at the edge; empty = no restriction (#616). */
  readonly geoRestrictionCountries?: string[];
}

export interface BackendConfig {
  /** @default 10000 */
  readonly apiThrottleRateLimit?: number;
  /** @default 5000 */
  readonly apiThrottleBurstLimit?: number;
  /** Per-method throttle rate for POST /api/chat. @default 200 */
  readonly chatThrottleRateLimit?: number;
  /** Per-method throttle burst for POST /api/chat. @default 400 */
  readonly chatThrottleBurstLimit?: number;
  /** Seconds. @default 30 */
  readonly lambdaTimeout?: number;
  /** MB. @default 512 */
  readonly lambdaMemorySize?: number;
  /** @default INFO (prod) / DEBUG (non-prod) */
  readonly logLevel?: string;
  /** @default true */
  readonly enableTracing?: boolean;
  readonly logRetentionDays?: logs.RetentionDays;
  readonly bedrockModelId?: string;
  readonly knowledgeBaseId?: string;
  /** @default true */
  readonly enableGuardrails?: boolean;
  readonly guardrailBlockedInputMessage?: string;
  readonly guardrailBlockedOutputMessage?: string;
  readonly guardrailAgentModelId?: string;
  /** Resolves bucket from SSM. @default false */
  readonly enableBm25?: boolean;
  /** Override; resolved from SSM when unset. */
  readonly bm25IndexBucket?: string;
  /** @default false */
  readonly hydeEnabled?: boolean;
  /** Defaults to bedrockModelId. */
  readonly hydeModelId?: string;
  /** "rag" (default) or "agent". */
  readonly searchMode?: string;
  /** Empty = load from local. */
  readonly agentSearchIndexBucket?: string;
  readonly langfuseHost?: string;
  readonly langfuseSecretName?: string;
  /** Last key rotation (UTC, YYYY-MM-DDTHH:MMZ); a change forces chat Lambda cold starts. */
  readonly langfuseKeyRotatedAt?: string;
  /** @default false */
  readonly otelIncludeContent?: boolean;
  /** DynamoDB item expiry. @default 30 */
  readonly conversationTtlDays?: number;
}

export interface WafConfig {
  /** @default true */
  readonly wafEnabled?: boolean;
  /** Requests per 5 min per IP. @default 500 */
  readonly wafRateLimitPerIp?: number;
  /** @default true */
  readonly wafBotControlEnabled?: boolean;
  /** Action per Web ACL and managed rule group. @default all 'count' */
  readonly wafManagedRuleActions?: WafManagedRuleActions;
  /** Rules kept on `count` per Web ACL and rule group. @default none */
  readonly wafRuleCountOverrides?: WafRuleCountOverrides;
  /** CloudFront WAF WebACL in us-east-1. @default true */
  readonly wafCloudfrontEnabled?: boolean;
}

export interface BudgetConfig {
  /** USD; AWS Budgets reports pre-discount. */
  readonly monthlyBudgetUsd: number;
  readonly thresholds: {
    readonly percentage: number;
    readonly notificationType: 'ACTUAL' | 'FORECASTED';
  }[];
}

/** Alarm on the Bedrock input-token sum of one model (#989). */
export interface BedrockTokenAlarmConfig {
  /** Value of the `ModelId` dimension in `AWS/Bedrock`. */
  readonly modelId: string;
  /** Alarm when the 5-minute sum is above this value. */
  readonly thresholdPer5Min: number;
  /** Consecutive breaching 5-minute periods. @default 3 */
  readonly evaluationPeriods?: number;
}

export interface MonitoringConfig {
  /** Legacy single recipient; prefer alertEmails. */
  readonly alertEmail?: string;
  readonly alertEmails?: string[];
  /** @default true */
  readonly enableEtlMonitoring: boolean;
  /** Prod only. */
  readonly budget?: BudgetConfig;
  /**
   * Daily budget pacing (#579) — auto-flips maintenance mode on prorated overspend.
   * Requires an SNS topic (via alertEmail/alertEmails).
   */
  readonly enableBudgetPacing?: boolean;
  /** USD per Cost Explorer (pre-discount, incl. tax). Defaults to the budget-alerts $7,000. */
  readonly budgetPacingMonthlyUsd?: number;
  /** Early cost-abuse signal (#989). Detection only, not a brake. */
  readonly bedrockTokenAlarm?: BedrockTokenAlarmConfig;
}

export interface ChatbotStackProps extends StackProps {
  readonly prefix: string;
  readonly envName: string;
  /** ECR account id (always the dev account). */
  readonly ecrAccount: string;

  readonly network?: NetworkConfig;
  readonly auth: AuthConfig;
  readonly frontend: FrontendConfig;
  readonly backend?: BackendConfig;
  readonly waf?: WafConfig;
  readonly monitoring?: MonitoringConfig;
}
