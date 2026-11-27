#!/usr/bin/env node
import 'source-map-support/register';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { EtlKnowledgeBaseStack } from '../lib/etl-kb-stack';
import { ChatbotStack } from '../lib/chatbot-stack';
import { CloudFrontWafStack } from '../lib/cloudfront-waf-stack';
import {
  getETLParameters,
  getChatbotParameters,
} from '../lib/utils/parameter-models';
import { loadEnvConfig } from '../lib/utils/env-config';
import { isProdEnv } from '../lib/config/chatbot-config';
import { configureProdPhysicalNameContext } from '../lib/config/retrieval-environment';
import { etlParametersMap, chatbotParametersMap } from '../parameter';

const app = new cdk.App();

const envName = app.node.tryGetContext('env') || 'dev';

// Normalize legacy `environment` context before any stack: without this, omitting
// the old flag in prod proposes a second set of `*-dev-*` resources.
configureProdPhysicalNameContext(app.node, envName);

// `demo` keeps `-prod` stack-name strings on purpose (#473/#504).
if (envName === 'demo') {
  console.warn(
    '\n⚠️  env=demo: prod/demo naming is intentionally mismatched — stacks are renate-*-prod, NOT renate-*-demo.\n' +
      '    See open ticket #504 before redeploying demo.\n',
  );
}

const repoRoot = path.resolve(__dirname, '..', '..');
const envConfig = loadEnvConfig(repoRoot, envName);
const etlParams = getETLParameters(app, envName, etlParametersMap, envConfig);
const chatbotParams = getChatbotParameters(app, envName, chatbotParametersMap, envConfig);

// #989: the token alarm watches exactly one ModelId. Without it, prod would
// synth silently without the alarm, so fail the synth instead.
function requireTokenAlarmModelId(modelId: string | undefined): string {
  if (!modelId) {
    throw new Error(
      `bedrockModelId missing for ${envName}: required for the token alarm (#989)`,
    );
  }
  return modelId;
}

const env = {
  account: etlParams.account,
  region: etlParams.region,
};

const etlStack = new EtlKnowledgeBaseStack(app, etlParams.etlStackName, {
  envName: etlParams.envName,
  kbStackName: etlParams.kbStackName,
  kbDescription: etlParams.kbDescription,
  vectorDimension: etlParams.vectorDimension,
  etlConfig: {
    lambdaTimeoutSeconds: etlParams.lambdaTimeoutSeconds,
    lambdaMemorySizeMb: etlParams.lambdaMemorySizeMb,
    batchSize: etlParams.batchSize,
    batchWindowSeconds: etlParams.batchWindowSeconds,
    visibilityTimeoutSeconds: etlParams.visibilityTimeoutSeconds,
    messageRetentionDays: etlParams.messageRetentionDays,
    maxReceiveCount: etlParams.maxReceiveCount,
    chunking: etlParams.chunking,
    contextualGrounding: etlParams.contextualGrounding,
    enrichment: etlParams.enrichment,
  },
  alertEmail: etlParams.alertEmail,
  retrievalHealthAlarmActionsEnabled:
    etlParams.retrievalHealthAlarmActionsEnabled,
  ...(isProdEnv(envName) && {
    alertEmails: [
      'renate@drv-bund.de',
      'ki-reha-anwendungsbetrieb@drv-bund.de',
    ],
  }),
  etlEcrAccount: etlParams.etlEcrAccount,
  env: env,
  description: etlParams.etlDescription,
  tags: {
    Project: 'Digibro',
    Service: 'BedrockKnowledgeBase',
    CDK: 'true',
  },
});

// CloudFront WebACLs must live in us-east-1 regardless of app region.
let cloudFrontWafStack: CloudFrontWafStack | undefined;
if (chatbotParams.wafCloudfrontEnabled !== false) {
  cloudFrontWafStack = new CloudFrontWafStack(
    app,
    `${chatbotParams.chatbotStackName}-cf-waf`,
    {
      prefix: chatbotParams.prefix,
      envName: chatbotParams.envName,
      rateLimitPerIp: chatbotParams.wafRateLimitPerIp,
      botControlEnabled: chatbotParams.wafBotControlEnabled,
      managedRuleActions: chatbotParams.wafManagedRuleActions.cloudfront,
      ruleCountOverrides: chatbotParams.wafRuleCountOverrides.cloudfront,
      env: { account: chatbotParams.account, region: 'us-east-1' },
      crossRegionReferences: true,
    },
  );
}

const chatbotStack = new ChatbotStack(app, chatbotParams.chatbotStackName, {
  prefix: chatbotParams.prefix,
  envName: chatbotParams.envName,
  ecrAccount: chatbotParams.ecrAccount,
  frontend: {
    origin: chatbotParams.frontendOrigin,
    domainName: chatbotParams.frontendDomainName,
    hostedZoneId: chatbotParams.hostedZoneId,
    hostedZoneName: chatbotParams.hostedZoneName,
    certificateArn: chatbotParams.frontendCertificateArn,
    dnsRecordName: chatbotParams.frontendDnsRecordName,
    enableIpV6: chatbotParams.enableIpV6,
    webAclId: cloudFrontWafStack?.webAclArn,
    geoRestrictionCountries: chatbotParams.geoRestrictionCountries,
  },
  auth: {
    userPoolDomainPrefix: chatbotParams.userPoolDomainPrefix,
    allowedSignUpEmailDomains: chatbotParams.allowedSignUpEmailDomains,
    selfSignUpEnabled: chatbotParams.selfSignUpEnabled,
    tokenValidityMinutes: chatbotParams.tokenValidityMinutes,
    anonymousAccess: chatbotParams.anonymousAccess,
    intern: chatbotParams.intern,
  },
  network: {
    vpcCidr: chatbotParams.vpcCidr,
    maxAzs: chatbotParams.maxAzs,
    natGateways: chatbotParams.natGateways,
  },
  backend: {
    lambdaTimeout: chatbotParams.lambdaTimeout,
    lambdaMemorySize: chatbotParams.lambdaMemorySize,
    logLevel: chatbotParams.logLevel,
    enableTracing: chatbotParams.enableTracing,
    apiThrottleRateLimit: chatbotParams.apiThrottleRateLimit,
    apiThrottleBurstLimit: chatbotParams.apiThrottleBurstLimit,
    chatThrottleRateLimit: chatbotParams.chatThrottleRateLimit,
    chatThrottleBurstLimit: chatbotParams.chatThrottleBurstLimit,
    bedrockModelId: chatbotParams.bedrockModelId,
    enableGuardrails: true,
    enableBm25: chatbotParams.enableBm25,
    bm25IndexBucket: chatbotParams.bm25IndexBucket,
    hydeEnabled: chatbotParams.hydeEnabled,
    hydeModelId: chatbotParams.hydeModelId,
    searchMode: chatbotParams.searchMode,
    agentSearchIndexBucket: chatbotParams.agentSearchIndexBucket,
    langfuseHost: chatbotParams.langfuseHost,
    langfuseSecretName: chatbotParams.langfuseSecretName,
    langfuseKeyRotatedAt: chatbotParams.langfuseKeyRotatedAt,
    otelIncludeContent: chatbotParams.otelIncludeContent,
    conversationTtlDays: chatbotParams.conversationTtlDays,
  },
  monitoring: {
    alertEmail: chatbotParams.alertEmail,
    ...(isProdEnv(envName) && {
      alertEmails: [
        'renate@drv-bund.de',
        'ki-reha-anwendungsbetrieb@drv-bund.de',
      ],
    }),
    enableEtlMonitoring: chatbotParams.enableEtlMonitoring,
    ...(isProdEnv(envName) && !chatbotParams.skipBudgetAlerts && {
      budget: {
        // $7,000 ≈ 5.000 € brutto after MwSt, EDP discount, FX, US tax.
        // Formula: 5000 / 1.19 / 0.725 * 1.14 * 1.154 ≈ $7.624; rounded down
        // so alerts fire slightly early. Revisit if FX or tax % shift.
        monthlyBudgetUsd: 7000,
        thresholds: [
          { percentage: 50, notificationType: 'FORECASTED' as const },
          { percentage: 70, notificationType: 'ACTUAL' as const },
          { percentage: 100, notificationType: 'ACTUAL' as const },
        ],
      },
    }),
    // Budget Pacing (#579): auto maintenance mode on daily overspend.
    // Uses the same $7,000/month as the budget alerts above.
    ...(isProdEnv(envName) && {
      enableBudgetPacing: true,
    }),
    // #989 Token alarm, prod only. Threshold from 62 days of prod data
    // (15.09.-18.11.2026): 5-min sums p50 0.17M, p99 1.17M, max 3.41M; would
    // have fired once (06.11.). 1.5M per 5 min ≈ 95 USD/day. Nova Lite is
    // left out: hourly jobs push it to ~2M. See milestone %42, ADR-003.
    ...(isProdEnv(envName) && {
      bedrockTokenAlarm: {
        modelId: requireTokenAlarmModelId(chatbotParams.bedrockModelId),
        thresholdPer5Min: 1_500_000,
        evaluationPeriods: 3,
      },
    }),
    // TODO(#578): TEMPORARY dev budget verifying Budget→SNS→Email chain.
    // Dev spend ~$1,500/month so 50% of $100 fires immediately. REMOVE in follow-up.
    ...(envName === 'dev' && {
      budget: {
        monthlyBudgetUsd: 100,
        thresholds: [
          { percentage: 50, notificationType: 'ACTUAL' as const },
        ],
      },
    }),
  },
  waf: {
    wafEnabled: chatbotParams.wafEnabled,
    wafRateLimitPerIp: chatbotParams.wafRateLimitPerIp,
    wafBotControlEnabled: chatbotParams.wafBotControlEnabled,
    wafManagedRuleActions: chatbotParams.wafManagedRuleActions,
    wafRuleCountOverrides: chatbotParams.wafRuleCountOverrides,
  },
  description: chatbotParams.chatbotDescription,
  env: env,
  crossRegionReferences: true,
  tags: {
    Project: 'Digibro',
    Service: 'ChatbotStack',
    CDK: 'true',
  },
});

cdk.Tags.of(app).add('Kostenstelle', chatbotParams.kostenstelle || '500050');
cdk.Tags.of(app).add('Kostentraeger', chatbotParams.kostentraeger || 'NCL701');
cdk.Tags.of(app).add('Sachkonto', chatbotParams.sachkonto || '7978801');
cdk.Tags.of(app).add('Projekt', chatbotParams.projekt || 'digibro');

app.synth();
