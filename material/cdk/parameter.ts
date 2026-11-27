import { ETLParameters, ChatbotParameters } from './lib/utils/parameter-models';

/**
 * Environment-specific ETL stack configurations
 * Add new environments by adding entries to this map (e.g., 'staging', 'prod')
 */
export const etlParametersMap = new Map<string, Partial<ETLParameters>>([
  [
    'dev',
    {
      envName: 'dev',
      account: '831926590742',
      region: 'eu-central-1',
      etlStackName: 'renate-etl-kb-dev',
      etlDescription: 'Development ETL Stack for Bedrock Knowledge Base',
      kbStackName: 'renate-bedrock-knowledge-base',
      kbDescription:
        'Development environment for Bedrock Knowledge Base with S3 Vector Storage',
      vectorDimension: 1024,
      lambdaTimeoutSeconds: 300,
      lambdaMemorySizeMb: 2048,
      batchSize: 10,
      batchWindowSeconds: 60,
      visibilityTimeoutSeconds: 600,
      messageRetentionDays: 4,
      maxReceiveCount: 3,
      kostenstelle: '500050',
      kostentraeger: 'NCL701',
      sachkonto: '7978801',
      projekt: 'digibro-dev',
      contextualGrounding: {
        enabled: false,
        modelId: 'eu.amazon.nova-pro-v1:0',
      },
      enrichment: {
        enabled: true,
        modelId: 'eu.amazon.nova-lite-v1:0',
      },
      etlEcrAccount: '831926590742',
    },
  ],
  [
    'qa',
    {
      envName: 'qa',
      account: '571600837515',
      region: 'eu-central-1',
      etlStackName: 'renate-etl-kb-qa',
      etlDescription: 'QA ETL Stack for Bedrock Knowledge Base',
      kbStackName: 'renate-bedrock-knowledge-base',
      kbDescription:
        'QA environment for Bedrock Knowledge Base with S3 Vector Storage',
      vectorDimension: 1024,
      lambdaTimeoutSeconds: 300,
      lambdaMemorySizeMb: 2048,
      batchSize: 10,
      batchWindowSeconds: 60,
      visibilityTimeoutSeconds: 600,
      messageRetentionDays: 4,
      maxReceiveCount: 3,
      kostenstelle: '500050',
      kostentraeger: 'NCL701',
      sachkonto: '7978801',
      projekt: 'digibro-dev',
      contextualGrounding: {
        enabled: false,
        modelId: 'eu.amazon.nova-pro-v1:0',
      },
      enrichment: {
        enabled: false,
        modelId: 'eu.amazon.nova-lite-v1:0',
      },
    },
  ],
  [
    // NOTE: This block was previously keyed as 'prod' but targets the demo account (254992224283).
    // Key renamed to 'demo' in #473. Stack-name strings kept as 'renate-etl-kb-prod' intentionally
    // to avoid CFN replacement of the live demo stack (Verena).
    // Physical rename (etlStackName → 'renate-etl-kb-demo', kbStackName suffix) deferred to:
    // https://gitlab.kilab-platform.de/renate/digibro-monorepo/-/issues/504
    'demo',
    {
      envName: 'demo',
      account: '254992224283',
      region: 'eu-central-1',
      // Stack name intentionally kept as '-prod' suffix to avoid CFN replacement of the live demo stack.
      // Physical rename (→ 'renate-etl-kb-demo') deferred to migration ticket #504.
      etlStackName: 'renate-etl-kb-prod',
      etlDescription: 'Demo ETL Stack for Bedrock Knowledge Base',
      // kbStackName intentionally kept without env suffix — adding a suffix replaces the Bedrock KB
      // + S3 vector store and triggers full re-ingest. Deferred to migration ticket (see note above).
      kbStackName: 'renate-bedrock-knowledge-base',
      kbDescription:
        'Demo environment for Bedrock Knowledge Base with S3 Vector Storage',
      vectorDimension: 1024,
      lambdaTimeoutSeconds: 300,
      lambdaMemorySizeMb: 2048,
      batchSize: 10,
      batchWindowSeconds: 60,
      visibilityTimeoutSeconds: 600,
      messageRetentionDays: 4,
      maxReceiveCount: 3,
      kostenstelle: '500050',
      kostentraeger: 'NCL701',
      sachkonto: '7978801',
      projekt: 'digibro-demo',
      contextualGrounding: {
        enabled: false,
        modelId: 'eu.amazon.nova-pro-v1:0',
      },
    },
  ],
  [
    'preprod',
    {
      envName: 'preprod',
      account: '271033482134',
      region: 'eu-central-1',
      etlStackName: 'renate-etl-kb-preprod',
      etlDescription: 'Preprod ETL Stack for Bedrock Knowledge Base',
      kbStackName: 'renate-bedrock-knowledge-base-preprod',
      kbDescription:
        'Preprod environment for Bedrock Knowledge Base with S3 Vector Storage',
      vectorDimension: 1024,
      lambdaTimeoutSeconds: 300,
      lambdaMemorySizeMb: 2048,
      batchSize: 10,
      batchWindowSeconds: 60,
      visibilityTimeoutSeconds: 600,
      messageRetentionDays: 4,
      maxReceiveCount: 3,
      kostenstelle: '500050',
      kostentraeger: 'NCL701',
      sachkonto: '7978801',
      projekt: 'digibro-preprod',
      contextualGrounding: {
        enabled: false,
        modelId: 'eu.amazon.nova-pro-v1:0',
      },
      enrichment: {
        enabled: false,
        modelId: 'eu.amazon.nova-lite-v1:0',
      },
    },
  ],
  [
    'prod',
    {
      envName: 'prod',
      account: '718036735727',
      region: 'eu-central-1',
      etlStackName: 'renate-etl-kb-prod',
      etlDescription: 'Production ETL Stack for Bedrock Knowledge Base',
      // Fresh prod account — env-suffixed KB stack name (mirrors preprod convention).
      // No CFN replacement risk in a new account.
      kbStackName: 'renate-bedrock-knowledge-base-prod',
      kbDescription:
        'Production environment for Bedrock Knowledge Base with S3 Vector Storage',
      vectorDimension: 1024,
      lambdaTimeoutSeconds: 300,
      lambdaMemorySizeMb: 2048,
      batchSize: 10,
      batchWindowSeconds: 60,
      visibilityTimeoutSeconds: 600,
      messageRetentionDays: 4,
      maxReceiveCount: 3,
      kostenstelle: '500050',
      kostentraeger: 'NCL701',
      sachkonto: '7978801',
      projekt: 'digibro-prod',
      contextualGrounding: {
        enabled: false,
        modelId: 'eu.amazon.nova-pro-v1:0',
      },
      // etlEcrAccount omitted → picks up schema default '831926590742'
      // (dev ECR account, cross-account pull wired in #496).
    },
  ],
]);

/**
 * Environment-specific Chatbot stack configurations
 * Add new environments by adding entries to this map (e.g., 'staging', 'prod')
 *
 * NOTE: Do NOT set feature flags (e.g. anonymousAccess) here.
 * Per-env flags belong in deployments/<env>/config.yaml — that file has
 * highest merge priority and overrides anything set in this map.
 * See docs/runbooks/feature_flags_config_yaml.md.
 */
export const chatbotParametersMap = new Map<string, Partial<ChatbotParameters>>(
  [
    [
      'dev',
      {
        envName: 'dev',
        account: '831926590742',
        region: 'eu-central-1',
        chatbotStackName: 'renate-chatbot-dev',
        chatbotDescription: 'Renate - AI Chatbot Frontend and Backend (Dev)',
        prefix: 'renate',
        userPoolDomainPrefix: 'chatbot-staging-auth',
        // #616 — dev intentionally left open (non-DACH testers, CI runners).
        geoRestrictionCountries: [],
        allowedSignUpEmailDomains: ['drv-bund.de', 'drv-bsh.de'],
        selfSignUpEnabled: true,
        tokenValidityMinutes: 60,
        // DSFA retention period for stored conversation data (six months).
        conversationTtlDays: 180,
        vpcCidr: '10.1.0.0/16',
        maxAzs: 2,
        natGateways: 1,
        lambdaTimeout: 28,
        lambdaMemorySize: 512,
        logLevel: 'INFO',
        enableTracing: true,
        apiThrottleRateLimit: 10000,
        apiThrottleBurstLimit: 5000,
        bedrockModelId: 'openai.gpt-oss-120b-1:0',
        enableBm25: true,
        hydeEnabled: false,
        searchMode: 'rag', // 'rag' = KB embedding search, 'agent' = agent-based document search
        enableIpV6: true,
        langfuseHost: 'https://langfuse-renate-dev.kilab-platform.de',
        langfuseSecretName: 'langfuse/dev/lambda-api-keys',
        // Explicitly approved: include prompt/response content in LangFuse
        // traces by default across all stages. Revisit per-stage (especially
        // Prod) if this default is later withdrawn.
        otelIncludeContent: true,
        wafEnabled: true,
        wafRateLimitPerIp: 100,
        wafBotControlEnabled: true,
        wafManagedRuleActions: {
          cloudfront: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
          regional: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
        },
        chatThrottleRateLimit: 50,
        chatThrottleBurstLimit: 100,
        wafCloudfrontEnabled: true,
        kostenstelle: '500050',
        kostentraeger: 'NCL701',
        sachkonto: '7978801',
        projekt: 'digibro-dev',
      },
    ],
    [
      'qa',
      {
        envName: 'qa',
        account: '571600837515',
        region: 'eu-central-1',
        chatbotStackName: 'renate-chatbot-qa',
        chatbotDescription: 'Renate - AI Chatbot Frontend and Backend (QA)',
        prefix: 'renate',
        userPoolDomainPrefix: 'chatbot-staging-auth',
        // #616 DACH geo restriction. Flip to [] via MR to break-glass.
        geoRestrictionCountries: ['DE', 'AT', 'CH'],
        allowedSignUpEmailDomains: [
          'drv-bund.de',
          'drv-bsh.de',
          'drv-md.de',
          'drv-hessen.de',
          'drv-nord.de',
          'drv-bw.de',
          'drv-bayernsued.de',
          'drv-berlin-brandenburg.de',
          'kbs.de',
          'drv-nordbayern.de',
          'drv-oldenburg-bremen.de',
          'drv-rheinland.de',
          'drv-rlp.de',
          'drv-saarland.de',
          'drv-schwaben.de',
          'drv-westfalen.de',
        ],
        selfSignUpEnabled: true,
        tokenValidityMinutes: 60,
        // DSFA retention period for stored conversation data (six months).
        conversationTtlDays: 180,
        vpcCidr: '10.1.0.0/16',
        maxAzs: 2,
        natGateways: 1,
        lambdaTimeout: 28,
        lambdaMemorySize: 512,
        logLevel: 'INFO',
        enableTracing: true,
        apiThrottleRateLimit: 10000,
        apiThrottleBurstLimit: 5000,
        bedrockModelId: 'openai.gpt-oss-120b-1:0',
        enableBm25: true,
        hydeEnabled: false,
        searchMode: 'rag', // 'rag' = KB embedding search, 'agent' = agent-based document search
        enableIpV6: true,
        langfuseHost: 'https://langfuse-renate-dev.kilab-platform.de',
        langfuseSecretName: 'langfuse/qa/lambda-api-keys',
        // Explicitly approved: include prompt/response content in LangFuse
        // traces by default across all stages. Revisit per-stage (especially
        // Prod) if this default is later withdrawn.
        otelIncludeContent: true,
        wafEnabled: true,
        wafRateLimitPerIp: 100,
        wafBotControlEnabled: true,
        wafManagedRuleActions: {
          cloudfront: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
          regional: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
        },
        chatThrottleRateLimit: 50,
        chatThrottleBurstLimit: 100,
        wafCloudfrontEnabled: true,
        kostenstelle: '500050',
        kostentraeger: 'NCL701',
        sachkonto: '7978801',
        projekt: 'digibro-dev',
      },
    ],
    [
      // NOTE: This block was previously keyed as 'prod' but targets the demo account (254992224283).
      // Key renamed to 'demo' in #473. Stack-name strings kept as 'renate-chatbot-prod' intentionally
      // to avoid CFN replacement of the live demo stack (Verena).
      // Physical rename (chatbotStackName → 'renate-chatbot-demo', userPoolDomainPrefix per-env) deferred to:
      // https://gitlab.kilab-platform.de/renate/digibro-monorepo/-/issues/504
      'demo',
      {
        envName: 'demo',
        account: '254992224283',
        region: 'eu-central-1',
        // Stack name intentionally kept as '-prod' suffix to avoid CFN replacement of the live demo stack.
        // Physical rename (→ 'renate-chatbot-demo') deferred to migration ticket #504.
        chatbotStackName: 'renate-chatbot-prod',
        chatbotDescription: 'Renate - AI Chatbot Frontend and Backend (Demo)',
        prefix: 'renate',
        // userPoolDomainPrefix intentionally kept as shared placeholder.
        // Per-env rename (→ 'renate-auth-demo') replaces the Cognito UserPoolDomain — deferred to migration ticket.
        userPoolDomainPrefix: 'chatbot-staging-auth',
        // #616 — demo intentionally left open pending stakeholder confirmation
        // (external attendees, AWS TAM). Flip via follow-up ticket after Verena signs off.
        geoRestrictionCountries: [],
        allowedSignUpEmailDomains: [
          'drv-bund.de',
          'drv-bsh.de',
          'drv-md.de',
          'drv-hessen.de',
          'drv-nord.de',
          'drv-bw.de',
          'drv-bayernsued.de',
          'drv-berlin-brandenburg.de',
          'kbs.de',
          'drv-nordbayern.de',
          'drv-oldenburg-bremen.de',
          'drv-rheinland.de',
          'drv-rlp.de',
          'drv-saarland.de',
          'drv-schwaben.de',
          'drv-westfalen.de',
        ],
        selfSignUpEnabled: true,
        tokenValidityMinutes: 60,
        vpcCidr: '10.1.0.0/16',
        maxAzs: 2,
        natGateways: 1,
        lambdaTimeout: 28,
        lambdaMemorySize: 512,
        logLevel: 'INFO',
        enableTracing: true,
        apiThrottleRateLimit: 10000,
        apiThrottleBurstLimit: 5000,
        bedrockModelId: 'openai.gpt-oss-120b-1:0',
        enableBm25: true,
        hydeEnabled: false,
        searchMode: 'rag', // 'rag' = KB embedding search, 'agent' = agent-based document search
        enableIpV6: true,
        // langfuseHost/langfuseSecretName intentionally omitted — no demo Langfuse instance exists.
        // Observability for demo will be addressed in #476.
        wafEnabled: true,
        wafRateLimitPerIp: 500,
        wafBotControlEnabled: true,
        wafManagedRuleActions: {
          cloudfront: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
          regional: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
        },
        chatThrottleRateLimit: 200,
        chatThrottleBurstLimit: 400,
        // Sizing: 2× max Lambda throughput (1000 concurrency / 10s avg = 100 rps).
        // Bedrock default quota (10k RPM = 167 rps) is the actual bottleneck.
        // When upgrading to 4000 concurrency + Bedrock quota increase → bump to 400/800.
        wafCloudfrontEnabled: true,
        kostenstelle: '500050',
        kostentraeger: 'NCL701',
        sachkonto: '7978801',
        projekt: 'digibro-demo',
      },
    ],
    [
      'preprod',
      {
        envName: 'preprod',
        account: '271033482134',
        region: 'eu-central-1',
        chatbotStackName: 'renate-chatbot-preprod',
        chatbotDescription:
          'Renate - AI Chatbot Frontend and Backend (Preprod)',
        prefix: 'renate',
        frontendOrigin: 'https://rentenchat.deutsche-rentenversicherung.de',
        frontendDomainName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z08197181YLWUAZDZBJQ',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
        frontendCertificateArn:
          'arn:aws:acm:us-east-1:271033482134:certificate/d78e46f6-f2c4-4ba5-91e6-1c4bf4c1a426',
        userPoolDomainPrefix: 'renate-auth-preprod',
        // #616 DACH geo restriction. Flip to [] via MR to break-glass.
        geoRestrictionCountries: ['DE', 'AT', 'CH'],
        allowedSignUpEmailDomains: [
          'drv-bund.de',
          'drv-bsh.de',
          'drv-md.de',
          'drv-hessen.de',
          'drv-nord.de',
          'drv-bw.de',
          'drv-bayernsued.de',
          'drv-berlin-brandenburg.de',
          'kbs.de',
          'drv-nordbayern.de',
          'drv-oldenburg-bremen.de',
          'drv-rheinland.de',
          'drv-rlp.de',
          'drv-saarland.de',
          'drv-schwaben.de',
          'drv-westfalen.de',
        ],
        selfSignUpEnabled: true,
        tokenValidityMinutes: 60,
        // DSFA retention period for stored conversation data (six months).
        conversationTtlDays: 180,
        vpcCidr: '10.1.0.0/16',
        maxAzs: 2,
        natGateways: 1,
        lambdaTimeout: 28,
        lambdaMemorySize: 512,
        logLevel: 'INFO',
        enableTracing: true,
        apiThrottleRateLimit: 10000,
        apiThrottleBurstLimit: 5000,
        bedrockModelId: 'openai.gpt-oss-120b-1:0',
        enableBm25: true,
        hydeEnabled: false,
        searchMode: 'rag',
        enableIpV6: true,
        // Using dev Langfuse instance until a dedicated preprod instance exists.
        // Follow-up: Dedicated Langfuse instance in (pre)prod account.
        langfuseHost: 'https://langfuse-renate-dev.kilab-platform.de',
        langfuseSecretName: 'langfuse/preprod/lambda-api-keys',
        // Explicitly approved: include prompt/response content in LangFuse
        // traces by default across all stages. Revisit per-stage (especially
        // Prod) if this default is later withdrawn.
        otelIncludeContent: true,
        wafEnabled: true,
        wafRateLimitPerIp: 100,
        wafBotControlEnabled: true,
        wafManagedRuleActions: {
          cloudfront: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
          regional: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
        },
        kostenstelle: '500050',
        kostentraeger: 'NCL701',
        sachkonto: '7978801',
        projekt: 'digibro-preprod',
      },
    ],
    [
      'prod',
      {
        envName: 'prod',
        account: '718036735727',
        region: 'eu-central-1',
        chatbotStackName: 'renate-chatbot-prod',
        chatbotDescription: 'Renate - AI Chatbot Frontend and Backend (Prod)',
        prefix: 'renate',
        // Globally unique Cognito UserPoolDomain (mirrors preprod pattern).
        userPoolDomainPrefix: 'renate-auth-prod',
        // #616 DACH geo restriction (matches preprod, citizen-facing prod DE/AT/CH).
        geoRestrictionCountries: ['DE', 'AT', 'CH'],
        // Cognito allowlist — mirrors preprod DRV DACH list. Only enforced when
        // selfSignUpEnabled=true; kept populated as an IdP-flow safety net.
        allowedSignUpEmailDomains: [
          'drv-bund.de',
          'drv-bsh.de',
          'drv-md.de',
          'drv-hessen.de',
          'drv-nord.de',
          'drv-bw.de',
          'drv-bayernsued.de',
          'drv-berlin-brandenburg.de',
          'kbs.de',
          'drv-nordbayern.de',
          'drv-oldenburg-bremen.de',
          'drv-rheinland.de',
          'drv-rlp.de',
          'drv-saarland.de',
          'drv-schwaben.de',
          'drv-westfalen.de',
        ],
        // Mirror preprod on day one — Self-Signup on to allow onboarding.
        // Flip to false in a follow-up MR when IdP-only sign-in is ready
        // (docs/prod-launch-plan.md §2 target end-state: "kein Self-Signup").
        selfSignUpEnabled: true,
        tokenValidityMinutes: 60,
        // DSFA retention period for stored conversation data (six months).
        conversationTtlDays: 180,
        vpcCidr: '10.1.0.0/16',
        maxAzs: 2,
        natGateways: 1,
        lambdaTimeout: 28,
        lambdaMemorySize: 512,
        logLevel: 'INFO',
        enableTracing: true,
        apiThrottleRateLimit: 10000,
        apiThrottleBurstLimit: 5000,
        bedrockModelId: 'openai.gpt-oss-120b-1:0',
        enableBm25: true,
        hydeEnabled: false,
        searchMode: 'rag',
        enableIpV6: true,
        // #773: Using the shared Dev LangFuse instance temporarily, mirroring
        // preprod, until the dedicated Prod instance (#745/#749/#751) is live.
        // Explicit compliance approval on record: Prod telemetry may share the
        // same 180-day retention as DynamoDB session data.
        langfuseHost: 'https://langfuse-renate-dev.kilab-platform.de',
        langfuseSecretName: 'langfuse/prod/lambda-api-keys',
        // #774: Explicitly approved — include prompt/response content in
        // LangFuse traces by default across all stages, including Prod. If
        // this default is later withdrawn for Prod, flip this back to false
        // and close #774.
        otelIncludeContent: true,
        // frontendDomainName + frontendOrigin + frontendCertificateArn remain
        // intentionally omitted until the coordinated CloudFront alias move.
        // The hosted zone below is used solely by the DNS-only preparation path.
        // DNS-only preparation: create A/AAAA alias records in the non-delegated
        // production hosted zone targeting the CloudFront distribution. This does
        // NOT attach the domain as an alternate name on CloudFront and does NOT
        // require a certificate. The records become active only after parent-zone
        // re-delegation (#555).
        frontendDnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
        wafEnabled: true,
        wafRateLimitPerIp: 500,
        wafBotControlEnabled: true,
        // Managed rule groups are enforced one by one per Web ACL (#994-#997,
        // ADR-003 im Wiki). Rate-based rules always block regardless.
        wafManagedRuleActions: {
          cloudfront: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
          regional: {
            common: 'count',
            knownBadInputs: 'count',
            ipReputation: 'count',
            botControl: 'count',
          },
        },
        chatThrottleRateLimit: 200,
        chatThrottleBurstLimit: 400,
        wafCloudfrontEnabled: true,
        kostenstelle: '500050',
        kostentraeger: 'NCL701',
        sachkonto: '7978801',
        projekt: 'digibro-prod',
      },
    ],
  ],
);
