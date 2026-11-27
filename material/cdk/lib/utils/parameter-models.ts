import { z } from 'zod';
import { App } from 'aws-cdk-lib';
import {
  DEFAULT_WAF_MANAGED_RULE_ACTIONS,
  findInvalidRuleCountOverrides,
} from '../config/waf-managed-rules';

// CDK --context flags always arrive as strings. z.boolean() rejects strings;
// z.coerce.boolean() wrongly maps "false" → true.
// Use this as a drop-in wrapper around z.boolean() for all context-sourced flags.
const zBoolContext = (defaultValue: boolean) =>
  z
    .preprocess((v) => {
      if (v === undefined || v === null) return undefined;
      if (typeof v === 'boolean') return v;
      if (v === 'true') return true;
      if (v === 'false') return false;
      throw new Error(`Expected boolean context value, got: ${String(v)}`);
    }, z.boolean().optional())
    .default(defaultValue);

const WafManagedRuleActionSchema = z.enum(['count', 'block']);

const WafRuleGroupActionsSchema = z
  .object({
    common: WafManagedRuleActionSchema.default('count'),
    knownBadInputs: WafManagedRuleActionSchema.default('count'),
    ipReputation: WafManagedRuleActionSchema.default('count'),
    botControl: WafManagedRuleActionSchema.default('count'),
  })
  .strict();

const WafManagedRuleActionsSchema = z
  .object({
    cloudfront: WafRuleGroupActionsSchema.default(
      DEFAULT_WAF_MANAGED_RULE_ACTIONS.cloudfront,
    ),
    regional: WafRuleGroupActionsSchema.default(
      DEFAULT_WAF_MANAGED_RULE_ACTIONS.regional,
    ),
  })
  .strict();

const WafRuleGroupCountOverridesSchema = z
  .object({
    common: z.array(z.string()).optional(),
    knownBadInputs: z.array(z.string()).optional(),
    ipReputation: z.array(z.string()).optional(),
    botControl: z.array(z.string()).optional(),
  })
  .strict();

const WafRuleCountOverridesSchema = z
  .object({
    cloudfront: WafRuleGroupCountOverridesSchema.optional(),
    regional: WafRuleGroupCountOverridesSchema.optional(),
  })
  .strict()
  .superRefine((overrides, ctx) => {
    for (const message of findInvalidRuleCountOverrides(overrides)) {
      ctx.addIssue({ code: 'custom', message });
    }
  });
const BaseParametersSchema = z.object({
  /** Environment name (dev, staging, prod) */
  envName: z
    .string()
    .min(1)
    .max(10)
    .regex(/^[a-zA-Z0-9]+$/, 'Environment name must be alphanumeric'),

  /** AWS account ID (12 digits) */
  account: z.string().regex(/^\d{12}$/, 'AWS account must be 12 digits'),

  region: z
    .string()
    .regex(/^[a-z]{2}-[a-z]+-\d{1}$/, 'Invalid AWS region format')
    .default('eu-central-1'),

  /** Cost center tags */
  kostenstelle: z.string().optional(),
  kostentraeger: z.string().optional(),
  sachkonto: z.string().optional(),
  projekt: z.string().optional(),
});

const ContextualGroundingConfigSchema = z.object({
  enabled: z.boolean().default(true),
  modelId: z.string().default('eu.amazon.nova-pro-v1:0'),
});

/**
 * When enabled, the CHUNK_MARKDOWN transform calls Nova Lite to add
 * section_title / keywords / colloquial_terms to chunks that lack
 * DITA-sourced metadata (Merkblätter, FAQ, header-less PDFs), improving
 * the BM25 semantic header. DITA brochures already carry this metadata
 * and are skipped.
 */
const EnrichmentConfigSchema = z.object({
  enabled: z.boolean().default(false),
  modelId: z.string().default('eu.amazon.nova-lite-v1:0'),
});

/**
 * When enabled=false (default):
 *   Transform Lambda outputs directly to ingestion bucket.
 *   Chunking is handled by CHUNK_MARKDOWN transform in the pipeline.
 *
 * When enabled=true:
 *   Transform Lambda outputs to intermediate bucket.
 *   A separate Chunking Lambda processes files before ingestion.
 *   Requires matching routes in config.yaml for the intermediate file types.
 *
 * Bedrock DataSource is always set to chunkingStrategy=NONE since
 * documents are pre-chunked by the ETL pipeline before reaching Bedrock.
 */
const ChunkingConfigSchema = z.object({
  enabled: z.boolean().default(false),
});

const ETLParametersSchema = BaseParametersSchema.extend({
  /** Stack name for ETL/KB stack */
  etlStackName: z.string().min(1),

  /** Stack description */
  etlDescription: z.string().default('ETL Stack for Bedrock Knowledge Base'),

  /** Knowledge Base stack name */
  kbStackName: z.string().default('renate-bedrock-knowledge-base'),

  /** Knowledge Base description */
  kbDescription: z
    .string()
    .default('Bedrock Knowledge Base with S3 Vector Storage'),

  /** Vector dimension for embeddings */
  vectorDimension: z.number().min(1).max(4096).default(1024),

  /** Lambda timeout for ETL processing in seconds */
  lambdaTimeoutSeconds: z.number().min(1).max(900).default(300),

  /** Lambda memory size in MB */
  lambdaMemorySizeMb: z.number().min(128).max(10240).default(2048),

  /** SQS batch size for ETL processing */
  batchSize: z.number().min(1).max(10000).default(10),

  /** SQS batch window in seconds */
  batchWindowSeconds: z.number().min(0).max(300).default(60),

  /** SQS visibility timeout in seconds */
  visibilityTimeoutSeconds: z.number().min(1).max(43200).default(600),

  /** SQS message retention in days */
  messageRetentionDays: z.number().min(1).max(14).default(4),

  /** SQS max receive count before DLQ */
  maxReceiveCount: z.number().min(1).max(1000).default(3),

  /** ETL chunking configuration */
  chunking: ChunkingConfigSchema.default({
    enabled: false,
  }),

  /** Contextual grounding configuration */
  contextualGrounding: ContextualGroundingConfigSchema.default({
    enabled: true,
    modelId: 'eu.amazon.nova-pro-v1:0',
  }),

  /** LLM-based chunk enrichment configuration */
  enrichment: EnrichmentConfigSchema.default({
    enabled: false,
    modelId: 'eu.amazon.nova-lite-v1:0',
  }),

  /** Email address for ETL monitoring alerts */
  alertEmail: z.string().email().optional(),

  /** List of email addresses for ETL monitoring alerts (prod) */
  alertEmails: z.array(z.string().email()).optional(),

  /** Wire prod retrieval-health alarms to the alert topic after heartbeat verification. */
  retrievalHealthAlarmActionsEnabled: zBoolContext(false),

  /** AWS account ID where the ETL ECR repository (renate-etl-lambda) lives (always dev account) */
  etlEcrAccount: z
    .string()
    .regex(/^\d{12}$/, 'ETL ECR account must be 12 digits')
    .default('831926590742'),
});

/**
 * Chatbot stack parameters including frontend, backend, and auth
 */
const ChatbotParametersSchema = BaseParametersSchema.extend({
  /** Stack name for Chatbot stack */
  chatbotStackName: z.string().min(1),

  /** Stack description */
  chatbotDescription: z.string().default('AI Chatbot Frontend and Backend'),

  /** Prefix for all resource names */
  prefix: z
    .string()
    .min(1)
    .max(20)
    .regex(
      /^[a-z0-9-]+$/,
      'Prefix must be lowercase alphanumeric with hyphens',
    ),

  /**
   * Optional additional origin to allow-list on the API Gateway CORS policy.
   * The primary origin is derived at runtime from the CloudFront distribution
   * via `frontend.getOrigin()` — either the custom domain (when set) or the
   * distribution's default hostname. Only set this when a second origin is
   * needed (e.g. a localhost URL for dev CORS or a legacy hostname during
   * cutover).
   */
  frontendOrigin: z.string().url().optional(),

  /** User Pool domain prefix for Cognito hosted UI */
  userPoolDomainPrefix: z.string().min(1),

  /** Allowed email domains for signup */
  allowedSignUpEmailDomains: z.array(z.string()).min(0).default([]),

  /**
   * ISO 3166-1 alpha-2 country codes allowed to access the CloudFront distribution.
   * Empty array = no geo restriction (open to the world). Non-empty = allowlist.
   * See #616.
   */
  geoRestrictionCountries: z
    .array(z.string().regex(/^[A-Z]{2}$/, 'ISO 3166-1 alpha-2 (uppercase)'))
    .default([]),

  /** Enable self-signup */
  selfSignUpEnabled: zBoolContext(true),

  /** Enable anonymous/public access — skips Cognito authorizer @default false */
  anonymousAccess: zBoolContext(false),

  /** Internal (DRV employee) mode — hides consent/disclaimer routes @default false */
  intern: zBoolContext(false),

  /** Token validity duration in minutes */
  tokenValidityMinutes: z.number().min(1).max(43200).default(60),

  /** VPC CIDR block */
  vpcCidr: z
    .string()
    .regex(/^(\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/)
    .default('10.1.0.0/16'),

  /** Number of Availability Zones */
  maxAzs: z.number().min(1).max(6).default(2),

  /** Number of NAT Gateways (1 = cost-optimized, 2+ = high availability) */
  natGateways: z.number().min(0).max(10).default(1),

  /** Lambda function timeout in seconds */
  lambdaTimeout: z.number().min(1).max(900).default(28),

  /** Lambda function memory size in MB */
  lambdaMemorySize: z.number().min(128).max(10240).default(512),

  /** Log level for Lambda functions */
  logLevel: z
    .enum(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'])
    .default('INFO'),

  /** Enable X-Ray tracing */
  enableTracing: zBoolContext(true),

  /** API Gateway throttle rate limit (requests per second) */
  apiThrottleRateLimit: z.number().min(1).max(10000).default(10000),

  /** API Gateway throttle burst limit (concurrent requests) */
  apiThrottleBurstLimit: z.number().min(1).max(5000).default(5000),

  /** Bedrock model ID for the agent */
  bedrockModelId: z
    .string()
    .min(1)
    .default('anthropic.claude-3-5-sonnet-20240620-v1:0'),

  /** Custom domain name for the frontend (optional) */
  frontendDomainName: z.string().optional(),

  /** Route53 hosted zone ID for the custom domain */
  hostedZoneId: z.string().optional(),

  /**
   * Explicit zone name for the imported hosted zone. Required when the
   * zone is not the immediate parent of `frontendDomainName` (i.e., a
   * subdomain delegation like `rentenchat.deutsche-rentenversicherung.de`
   * hosted as its own zone). If omitted, the zone name is derived from
   * `frontendDomainName` by stripping the leftmost label.
   */
  hostedZoneName: z.string().optional(),

  /**
   * ARN of a pre-existing ACM certificate to import. Overrides the default
   * "create + DNS-validate a fresh ACM cert" path. Use when the CA is not
   * ACM (e.g., a Telekom Security cert imported into ACM). Must be in
   * us-east-1 for CloudFront edge distributions.
   */
  frontendCertificateArn: z.string().optional(),

  /**
   * Zone-apex record name for DNS-only preparation (pre-cutover).
   * Creates A/AAAA alias records in the hosted zone pointing to the
   * CloudFront distribution WITHOUT attaching the domain as an alternate
   * name on CloudFront and without requiring a certificate.
   * Must be a fully-qualified domain name matching the hosted zone name.
   */
  frontendDnsRecordName: z.string().min(1).optional(),

  /** Enable IPv6 for CloudFront distribution */
  enableIpV6: zBoolContext(true),

  /** Knowledge Base ID (imported from ETL stack) */
  knowledgeBaseId: z.string().optional(),

  /** Enable BM25 hybrid search @default false */
  enableBm25: zBoolContext(false),

  /** S3 bucket name override for BM25 index (resolved from SSM if not set) */
  bm25IndexBucket: z.string().optional(),

  /** Enable HyDE (Hypothetical Document Embeddings) for KB retrieval */
  hydeEnabled: zBoolContext(false),

  /** Bedrock model ID for HyDE document generation (defaults to bedrockModelId) */
  hydeModelId: z.string().optional(),

  /** Search mode: "rag" or "agent" for agent-based document search */
  searchMode: z.enum(['rag', 'agent']).default('rag'),

  /** S3 bucket for agent search index (empty = load from local) */
  agentSearchIndexBucket: z.string().optional(),

  langfuseHost: z.string().url().optional(),
  langfuseSecretName: z.string().optional(),
  /**
   * UTC timestamp (YYYY-MM-DDTHH:MMZ) of the last LangFuse key rotation for
   * this stage. Changing it changes the Lambda configuration and thereby
   * forces fresh execution environments, which re-read the secret at cold
   * start (#979). Minute precision so a failed rotation can be retried on
   * the same day with a new value.
   */
  langfuseKeyRotatedAt: z
    .string()
    .regex(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$/,
      'must be YYYY-MM-DDTHH:MMZ (UTC)',
    )
    .refine((v) => {
      const parsed = new Date(v.replace('Z', ':00Z'));
      return (
        !Number.isNaN(parsed.getTime()) &&
        parsed.toISOString().startsWith(v.slice(0, 16))
      );
    }, 'must be a valid UTC date and time')
    .optional(),
  otelIncludeContent: zBoolContext(false),

  /** Email address for monitoring alerts */
  alertEmail: z.string().email().optional(),

  /** List of email addresses for monitoring alerts (prod) */
  alertEmails: z.array(z.string().email()).optional(),

  /** Enable WAF WebACL for API Gateway */
  wafEnabled: zBoolContext(true),

  /** WAF rate limit per IP (requests per 5 min window) */
  wafRateLimitPerIp: z.number().min(100).max(10000).default(500),

  /** Enable Bot Control managed rule group */
  wafBotControlEnabled: zBoolContext(true),

  /**
   * Action per Web ACL (`cloudfront`, `regional`) and managed rule group
   * (`common`, `knownBadInputs`, `ipReputation`, `botControl`): `count`
   * (log only) or `block` (#988). Omitted entries stay on `count`.
   * Only settable in cdk/parameter.ts.
   */
  wafManagedRuleActions: WafManagedRuleActionsSchema.default(
    DEFAULT_WAF_MANAGED_RULE_ACTIONS,
  ),

  /**
   * Rules kept on `count` inside a rule group, per Web ACL and rule group,
   * rendered as RuleActionOverrides. Unknown rule names fail the synth
   * (AWS WAF itself ignores unknown names silently). Only settable in
   * cdk/parameter.ts.
   */
  wafRuleCountOverrides: WafRuleCountOverridesSchema.default({}),

  /** Enable CloudFront WAF WebACL (deployed in us-east-1) @default true */
  wafCloudfrontEnabled: zBoolContext(true),

  /** AWS account ID where the ECR repository lives (always dev account) */
  ecrAccount: z
    .string()
    .regex(/^\d{12}$/, 'ECR account must be 12 digits')
    .default('831926590742'),

  /** Per-method throttle rate limit for POST /api/chat (requests per second) */
  chatThrottleRateLimit: z.number().min(10).max(10000).default(200),

  /** Per-method throttle burst limit for POST /api/chat (concurrent requests) */
  chatThrottleBurstLimit: z.number().min(10).max(10000).default(400),

  /** Enable ETL monitoring widgets in the CloudWatch dashboard */
  enableEtlMonitoring: zBoolContext(true),

  /** Skip AWS Budgets resource creation (workaround for SCP denying budgets:ModifyBudget) */
  skipBudgetAlerts: zBoolContext(false),

  /** Conversation TTL in days (DynamoDB item expiry) @default 30 */
  conversationTtlDays: z.number().min(1).max(365).default(30),
});

export type BaseParameters = z.infer<typeof BaseParametersSchema>;
export type ETLParameters = z.infer<typeof ETLParametersSchema>;
export type ChatbotParameters = z.infer<typeof ChatbotParametersSchema>;

export interface ApplicationParameters {
  etl: ETLParameters;
  chatbot: ChatbotParameters;
}

/**
 * Resolve priority: parameter map → CDK context → config.yaml overrides → Zod defaults.
 * overrides is the highest-priority layer.
 */
export function getETLParameters(
  app: App,
  envName?: string,
  paramsMap?: Map<string, Partial<ETLParameters>>,
  overrides?: Record<string, unknown>,
): ETLParameters {
  let inputParams: Partial<ETLParameters> = {};

  if (envName && paramsMap) {
    const mapParams = paramsMap.get(envName);
    if (mapParams) {
      inputParams = { ...mapParams };
    } else if (paramsMap.has('default')) {
      inputParams = { ...paramsMap.get('default') };
    }
  }

  const contextParams: Partial<ETLParameters> = {
    envName: envName || app.node.tryGetContext('envName'),
    account: app.node.tryGetContext('account'),
    region: app.node.tryGetContext('region'),
    etlStackName: app.node.tryGetContext('etlStackName'),
    kbStackName: app.node.tryGetContext('kbStackName'),
    vectorDimension: app.node.tryGetContext('vectorDimension'),
    lambdaTimeoutSeconds: app.node.tryGetContext('lambdaTimeoutSeconds'),
    lambdaMemorySizeMb: app.node.tryGetContext('lambdaMemorySizeMb'),
    batchSize: app.node.tryGetContext('batchSize'),
    kostenstelle: app.node.tryGetContext('kostenstelle'),
    kostentraeger: app.node.tryGetContext('kostentraeger'),
    sachkonto: app.node.tryGetContext('sachkonto'),
    projekt: app.node.tryGetContext('projekt'),
    alertEmail: app.node.tryGetContext('alertEmail'),
    etlEcrAccount: app.node.tryGetContext('etlEcrAccount'),
    retrievalHealthAlarmActionsEnabled: app.node.tryGetContext(
      'retrievalHealthAlarmActionsEnabled',
    ),
  };

  const mergedParams = {
    ...contextParams,
    ...inputParams,
    ...(overrides ?? {}),
  };

  // Drop undefined so Zod applies schema defaults.
  const cleanedParams = Object.fromEntries(
    Object.entries(mergedParams).filter(([_, v]) => v !== undefined),
  );

  try {
    return ETLParametersSchema.parse(cleanedParams);
  } catch (error) {
    if (error instanceof z.ZodError) {
      const errorMessages = error.issues
        .map((e: z.ZodIssue) => `${e.path.join('.')}: ${e.message}`)
        .join(', ');
      throw new Error(
        `ETL parameter validation failed for environment '${envName || 'default'}': ${errorMessages}`,
        { cause: error },
      );
    }
    throw error;
  }
}

/**
 * Resolve priority: parameter map → CDK context → config.yaml overrides → Zod defaults.
 */
export function getChatbotParameters(
  app: App,
  envName?: string,
  paramsMap?: Map<string, Partial<ChatbotParameters>>,
  overrides?: Record<string, unknown>,
): ChatbotParameters {
  let inputParams: Partial<ChatbotParameters> = {};

  if (envName && paramsMap) {
    const mapParams = paramsMap.get(envName);
    if (mapParams) {
      inputParams = { ...mapParams };
    } else if (paramsMap.has('default')) {
      inputParams = { ...paramsMap.get('default') };
    }
  }

  const contextParams: Partial<ChatbotParameters> = {
    envName: envName || app.node.tryGetContext('envName'),
    account: app.node.tryGetContext('account'),
    region: app.node.tryGetContext('region'),
    chatbotStackName: app.node.tryGetContext('chatbotStackName'),
    prefix: app.node.tryGetContext('prefix'),
    frontendOrigin: app.node.tryGetContext('frontendOrigin'),
    userPoolDomainPrefix: app.node.tryGetContext('userPoolDomainPrefix'),
    allowedSignUpEmailDomains: app.node.tryGetContext(
      'allowedSignUpEmailDomains',
    ),
    geoRestrictionCountries: app.node.tryGetContext('geoRestrictionCountries'),
    selfSignUpEnabled: app.node.tryGetContext('selfSignUpEnabled'),
    tokenValidityMinutes: app.node.tryGetContext('tokenValidityMinutes'),
    vpcCidr: app.node.tryGetContext('vpcCidr'),
    maxAzs: app.node.tryGetContext('maxAzs'),
    natGateways: app.node.tryGetContext('natGateways'),
    lambdaTimeout: app.node.tryGetContext('lambdaTimeout'),
    lambdaMemorySize: app.node.tryGetContext('lambdaMemorySize'),
    logLevel: app.node.tryGetContext('logLevel'),
    enableTracing: app.node.tryGetContext('enableTracing'),
    apiThrottleRateLimit: app.node.tryGetContext('apiThrottleRateLimit'),
    apiThrottleBurstLimit: app.node.tryGetContext('apiThrottleBurstLimit'),
    bedrockModelId: app.node.tryGetContext('bedrockModelId'),
    frontendDomainName: app.node.tryGetContext('frontendDomainName'),
    hostedZoneId: app.node.tryGetContext('hostedZoneId'),
    hostedZoneName: app.node.tryGetContext('hostedZoneName'),
    frontendCertificateArn: app.node.tryGetContext('frontendCertificateArn'),
    frontendDnsRecordName: app.node.tryGetContext('frontendDnsRecordName'),
    enableIpV6: app.node.tryGetContext('enableIpV6'),
    knowledgeBaseId: app.node.tryGetContext('knowledgeBaseId'),
    bm25IndexBucket: app.node.tryGetContext('bm25IndexBucket'),
    hydeEnabled: app.node.tryGetContext('hydeEnabled'),
    hydeModelId: app.node.tryGetContext('hydeModelId'),
    langfuseHost: app.node.tryGetContext('langfuseHost'),
    langfuseSecretName: app.node.tryGetContext('langfuseSecretName'),
    langfuseKeyRotatedAt: app.node.tryGetContext('langfuseKeyRotatedAt'),
    otelIncludeContent: app.node.tryGetContext('otelIncludeContent'),
    alertEmail: app.node.tryGetContext('alertEmail'),
    ecrAccount: app.node.tryGetContext('ecrAccount'),
    enableEtlMonitoring: app.node.tryGetContext('enableEtlMonitoring'),
    skipBudgetAlerts: app.node.tryGetContext('skipBudgetAlerts'),
    wafEnabled: app.node.tryGetContext('wafEnabled'),
    wafRateLimitPerIp: app.node.tryGetContext('wafRateLimitPerIp'),
    wafBotControlEnabled: app.node.tryGetContext('wafBotControlEnabled'),
    chatThrottleRateLimit: app.node.tryGetContext('chatThrottleRateLimit'),
    chatThrottleBurstLimit: app.node.tryGetContext('chatThrottleBurstLimit'),
    wafCloudfrontEnabled: app.node.tryGetContext('wafCloudfrontEnabled'),
    conversationTtlDays: app.node.tryGetContext('conversationTtlDays'),
    anonymousAccess: app.node.tryGetContext('anonymousAccess'),
    intern: app.node.tryGetContext('intern'),

    kostenstelle: app.node.tryGetContext('kostenstelle'),
    kostentraeger: app.node.tryGetContext('kostentraeger'),
    sachkonto: app.node.tryGetContext('sachkonto'),
    projekt: app.node.tryGetContext('projekt'),
  };

  const mergedParams = {
    ...contextParams,
    ...inputParams,
    ...(overrides ?? {}),
  };

  // Removed in #988. Fail instead of silently ignoring a leftover setting.
  if (
    app.node.tryGetContext('wafRuleAction') !== undefined ||
    'wafRuleAction' in inputParams ||
    'wafRuleAction' in (overrides ?? {})
  ) {
    throw new Error(
      `wafRuleAction was removed (#988); use wafManagedRuleActions and wafRuleCountOverrides (environment '${envName || 'default'}')`,
    );
  }

  // Only cdk/parameter.ts may set these. parameter.ts wins over --context, so
  // a context value would be silently overridden; config.yaml would silently
  // win over parameter.ts. WAF enforcement must be one reviewed place.
  for (const key of ['wafManagedRuleActions', 'wafRuleCountOverrides']) {
    if (app.node.tryGetContext(key) !== undefined || key in (overrides ?? {})) {
      throw new Error(
        `${key} can only be set in cdk/parameter.ts, not via --context or config.yaml (environment '${envName || 'default'}')`,
      );
    }
  }

  // Drop undefined so Zod applies schema defaults.
  const cleanedParams = Object.fromEntries(
    Object.entries(mergedParams).filter(([_, v]) => v !== undefined),
  );

  try {
    return ChatbotParametersSchema.parse(cleanedParams);
  } catch (error) {
    if (error instanceof z.ZodError) {
      const errorMessages = error.issues
        .map((e: z.ZodIssue) => `${e.path.join('.')}: ${e.message}`)
        .join(', ');
      throw new Error(
        `Chatbot parameter validation failed for environment '${envName || 'default'}': ${errorMessages}`,
        { cause: error },
      );
    }
    throw error;
  }
}

export function getApplicationParameters(
  app: App,
  envName?: string,
  etlParamsMap?: Map<string, Partial<ETLParameters>>,
  chatbotParamsMap?: Map<string, Partial<ChatbotParameters>>,
): ApplicationParameters {
  return {
    etl: getETLParameters(app, envName, etlParamsMap),
    chatbot: getChatbotParameters(app, envName, chatbotParamsMap),
  };
}
