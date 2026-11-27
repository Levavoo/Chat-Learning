import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { CloudFrontWafConstruct } from '../../lib/constructs/waf-cloudfront';
import { WafRuleGroupActions } from '../../lib/config/waf-managed-rules';

const ALL_COUNT: WafRuleGroupActions = {
  common: 'count',
  knownBadInputs: 'count',
  ipReputation: 'count',
  botControl: 'count',
};

describe('CloudFrontWafConstruct', () => {
  let app: App;
  let stack: Stack;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'us-east-1' },
    });
  });

  function createWaf(
    overrides: Partial<
      ConstructorParameters<typeof CloudFrontWafConstruct>[2]
    > = {},
  ) {
    return new CloudFrontWafConstruct(stack, 'TestCfWaf', {
      prefix: 'renate',
      envName: 'dev',
      rateLimitPerIp: 100,
      botControlEnabled: true,
      managedRuleActions: ALL_COUNT,
      ...overrides,
    });
  }

  test('creates WebACL with scope CLOUDFRONT and default action ALLOW', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Scope: 'CLOUDFRONT',
      DefaultAction: { Allow: {} },
      Name: 'renate-cf-waf-dev',
    });
  });

  test('rate limit rule scoped to POST method only', () => {
    createWaf({ rateLimitPerIp: 500 });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'RateLimitPerIP',
          Priority: 0,
          Statement: {
            RateBasedStatement: {
              Limit: 500,
              AggregateKeyType: 'IP',
              ScopeDownStatement: {
                ByteMatchStatement: {
                  SearchString: 'POST',
                  FieldToMatch: { Method: {} },
                  PositionalConstraint: 'EXACTLY',
                  TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                },
              },
            },
          },
        }),
      ]),
    });
  });

  test('rate limit action is BLOCK with 429 response', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'RateLimitPerIP',
          Action: {
            Block: {
              CustomResponse: {
                ResponseCode: 429,
                CustomResponseBodyKey: 'rate-limit-response',
              },
            },
          },
        }),
      ]),
    });
  });

  test('includes 3 managed rule groups', () => {
    createWaf({ botControlEnabled: false });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'AWSManagedRulesCommonRuleSet',
          Priority: 1,
        }),
        Match.objectLike({
          Name: 'AWSManagedRulesKnownBadInputsRuleSet',
          Priority: 2,
        }),
        Match.objectLike({
          Name: 'AWSManagedRulesAmazonIpReputationList',
          Priority: 3,
        }),
      ]),
    });
  });

  function managedRules(): Record<string, Record<string, unknown>> {
    const webAcl = Object.values(
      Template.fromStack(stack).findResources('AWS::WAFv2::WebACL'),
    )[0];
    const rules = webAcl.Properties.Rules as Array<Record<string, unknown>>;
    return Object.fromEntries(
      rules
        .filter((r) => r.OverrideAction !== undefined)
        .map((r) => [r.Name as string, r]),
    );
  }

  test('all rule groups use Count when every action is count', () => {
    createWaf({ managedRuleActions: ALL_COUNT });
    const rules = managedRules();
    expect(Object.keys(rules)).toHaveLength(4);
    for (const rule of Object.values(rules)) {
      expect(rule.OverrideAction).toEqual({ Count: {} });
    }
  });

  test('block for one rule group yields OverrideAction None only there', () => {
    createWaf({ managedRuleActions: { ...ALL_COUNT, botControl: 'block' } });
    const rules = managedRules();
    expect(rules.AWSManagedRulesBotControlRuleSet.OverrideAction).toEqual({
      None: {},
    });
    expect(rules.AWSManagedRulesCommonRuleSet.OverrideAction).toEqual({
      Count: {},
    });
    expect(rules.AWSManagedRulesKnownBadInputsRuleSet.OverrideAction).toEqual({
      Count: {},
    });
    expect(rules.AWSManagedRulesAmazonIpReputationList.OverrideAction).toEqual({
      Count: {},
    });
  });

  test('rule count override yields RuleActionOverrides with Count', () => {
    createWaf({
      managedRuleActions: { ...ALL_COUNT, botControl: 'block' },
      ruleCountOverrides: { botControl: ['SignalNonBrowserUserAgent'] },
    });
    expect(managedRules().AWSManagedRulesBotControlRuleSet).toMatchObject({
      Statement: {
        ManagedRuleGroupStatement: {
          RuleActionOverrides: [
            { Name: 'SignalNonBrowserUserAgent', ActionToUse: { Count: {} } },
          ],
        },
      },
    });
  });

  test('unknown rule name in count overrides throws', () => {
    expect(() =>
      createWaf({ ruleCountOverrides: { ipReputation: ['AWSManagedIPList'] } }),
    ).toThrow(/unknown rule name 'AWSManagedIPList'/);
  });

  test('Bot Control present when botControlEnabled is true', () => {
    createWaf({ botControlEnabled: true });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'AWSManagedRulesBotControlRuleSet',
          Priority: 4,
        }),
      ]),
    });
  });

  test('Bot Control NOT present when botControlEnabled is false', () => {
    createWaf({ botControlEnabled: false });
    const template = Template.fromStack(stack);
    const webAcls = template.findResources('AWS::WAFv2::WebACL');
    const webAcl = Object.values(webAcls)[0];
    const rules = webAcl.Properties.Rules as Array<{ Name: string }>;
    const botRule = rules.find(
      (r) => r.Name === 'AWSManagedRulesBotControlRuleSet',
    );
    expect(botRule).toBeUndefined();
  });

  test('does NOT create WebACLAssociation (CloudFront uses webAclId prop)', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.resourceCountIs('AWS::WAFv2::WebACLAssociation', 0);
  });

  test('exports WebACL ARN as CfnOutput', () => {
    createWaf();
    const template = Template.fromStack(stack);
    const outputs = template.findOutputs('*');
    const wafOutput = Object.entries(outputs).find(([key]) =>
      key.includes('CloudFrontWafWebAclArn'),
    );
    expect(wafOutput).toBeDefined();
    expect(wafOutput![1].Description).toBe('CloudFront WAF WebACL ARN');
  });
});
