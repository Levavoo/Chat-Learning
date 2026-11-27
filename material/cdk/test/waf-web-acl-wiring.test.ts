import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { ChatbotStack } from '../lib/chatbot-stack';
import { WafManagedRuleActions } from '../lib/config/waf-managed-rules';

// Different actions per Web ACL, so a swapped or wrong slice shows up (#988).
const ACTIONS: WafManagedRuleActions = {
  cloudfront: {
    common: 'block',
    knownBadInputs: 'count',
    ipReputation: 'count',
    botControl: 'count',
  },
  regional: {
    common: 'count',
    knownBadInputs: 'count',
    ipReputation: 'block',
    botControl: 'count',
  },
};

function overrideActions(template: Template): Record<string, unknown> {
  const webAcl = Object.values(template.findResources('AWS::WAFv2::WebACL'))[0];
  const rules = webAcl.Properties.Rules as Array<Record<string, unknown>>;
  return Object.fromEntries(
    rules
      .filter((r) => r.OverrideAction !== undefined)
      .map((r) => [r.Name as string, r.OverrideAction]),
  );
}

describe('WAF actions reach the right Web ACL', () => {
  test('ChatbotStack uses the regional slice', () => {
    const app = new App();
    const stack = new ChatbotStack(app, 'WiringStack', {
      prefix: 'test',
      envName: 'dev',
      ecrAccount: '123456789012',
      frontend: { origin: 'http://localhost:4200' },
      auth: { userPoolDomainPrefix: 'test-wiring-dev' },
      waf: {
        wafManagedRuleActions: ACTIONS,
        wafRuleCountOverrides: {
          cloudfront: { common: ['SizeRestrictions_BODY'] },
          regional: { ipReputation: ['AWSManagedIPDDoSList'] },
        },
      },
      env: { account: '123456789012', region: 'eu-central-1' },
    });
    const template = Template.fromStack(stack);
    expect(overrideActions(template)).toEqual({
      AWSManagedRulesCommonRuleSet: { Count: {} },
      AWSManagedRulesKnownBadInputsRuleSet: { Count: {} },
      AWSManagedRulesAmazonIpReputationList: { None: {} },
      AWSManagedRulesBotControlRuleSet: { Count: {} },
    });
    const webAcl = Object.values(
      template.findResources('AWS::WAFv2::WebACL'),
    )[0];
    expect(webAcl.Properties.Scope).toBe('REGIONAL');
    const withOverrides = (
      webAcl.Properties.Rules as Array<{
        Name: string;
        Statement: { ManagedRuleGroupStatement?: Record<string, unknown> };
      }>
    )
      .filter((r) => r.Statement.ManagedRuleGroupStatement?.RuleActionOverrides)
      .map((r) => r.Name);
    expect(withOverrides).toEqual(['AWSManagedRulesAmazonIpReputationList']);
  });

  test('bin/infrastructure.ts passes each slice to its Web ACL', () => {
    // Runs the real entry point with the real parameter map, only the WAF
    // actions of dev replaced. Catches a swapped .cloudfront/.regional there.
    const outdir = fs.mkdtempSync(path.join(os.tmpdir(), 'waf-wiring-'));
    const saved = {
      ctx: process.env.CDK_CONTEXT_JSON,
      out: process.env.CDK_OUTDIR,
    };
    process.env.CDK_CONTEXT_JSON = JSON.stringify({
      env: 'dev',
      etlImageTag: 'v0.0.0',
    });
    process.env.CDK_OUTDIR = outdir;
    try {
      jest.isolateModules(() => {
        const real = jest.requireActual('../parameter');
        const map = new Map(real.chatbotParametersMap);
        map.set('dev', {
          ...real.chatbotParametersMap.get('dev'),
          wafManagedRuleActions: ACTIONS,
        });
        jest.doMock('../parameter', () => ({
          ...real,
          chatbotParametersMap: map,
        }));
        require('../bin/infrastructure');
      });
      const read = (name: string) =>
        Template.fromJSON(
          JSON.parse(
            fs.readFileSync(path.join(outdir, `${name}.template.json`), 'utf8'),
          ),
        );
      expect(overrideActions(read('renate-chatbot-dev-cf-waf'))).toEqual({
        AWSManagedRulesCommonRuleSet: { None: {} },
        AWSManagedRulesKnownBadInputsRuleSet: { Count: {} },
        AWSManagedRulesAmazonIpReputationList: { Count: {} },
        AWSManagedRulesBotControlRuleSet: { Count: {} },
      });
      expect(overrideActions(read('renate-chatbot-dev'))).toEqual({
        AWSManagedRulesCommonRuleSet: { Count: {} },
        AWSManagedRulesKnownBadInputsRuleSet: { Count: {} },
        AWSManagedRulesAmazonIpReputationList: { None: {} },
        AWSManagedRulesBotControlRuleSet: { Count: {} },
      });
    } finally {
      jest.dontMock('../parameter');
      for (const [key, value] of [
        ['CDK_CONTEXT_JSON', saved.ctx],
        ['CDK_OUTDIR', saved.out],
      ] as const) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
      fs.rmSync(outdir, { recursive: true, force: true });
    }
  }, 300_000);
});
