import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { WafConstruct } from '../../lib/constructs/waf';
import { WafRuleGroupActions } from '../../lib/config/waf-managed-rules';

const ALL_COUNT: WafRuleGroupActions = {
  common: 'count',
  knownBadInputs: 'count',
  ipReputation: 'count',
  botControl: 'count',
};
const ALL_BLOCK: WafRuleGroupActions = {
  common: 'block',
  knownBadInputs: 'block',
  ipReputation: 'block',
  botControl: 'block',
};

describe('WafConstruct', () => {
  let app: App;
  let stack: Stack;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
  });

  function createWaf(
    overrides: Partial<ConstructorParameters<typeof WafConstruct>[2]> = {},
  ) {
    return new WafConstruct(stack, 'TestWaf', {
      prefix: 'renate',
      envName: 'dev',
      rateLimitPerIp: 100,
      botControlEnabled: true,
      managedRuleActions: ALL_COUNT,
      apiGatewayStageArn:
        'arn:aws:apigateway:eu-central-1::/restapis/abc123/stages/prod',
      ...overrides,
    });
  }

  test('creates WebACL with scope REGIONAL and default action ALLOW', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Scope: 'REGIONAL',
      DefaultAction: { Allow: {} },
      Name: 'renate-waf-dev',
    });
  });

  test('configures custom response bodies', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      CustomResponseBodies: {
        'rate-limit-response': {
          ContentType: 'APPLICATION_JSON',
          Content: Match.stringLikeRegexp('rate_limit_exceeded'),
        },
      },
    });
  });

  test('rate limit rule uses FORWARDED_IP and covers all methods on /api/chat', () => {
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
              AggregateKeyType: 'FORWARDED_IP',
              ForwardedIPConfig: {
                HeaderName: 'X-Forwarded-For',
                FallbackBehavior: 'MATCH',
              },
              ScopeDownStatement: {
                ByteMatchStatement: {
                  SearchString: '/api/chat',
                  FieldToMatch: { UriPath: {} },
                  PositionalConstraint: 'STARTS_WITH',
                  TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                },
              },
            },
          },
        }),
      ]),
    });
  });

  test('rate limit action is always BLOCK with 429 response', () => {
    createWaf({ managedRuleActions: ALL_BLOCK }); // Even when rule groups block, rate limit uses custom 429
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

  test('includes 3 managed rule groups with correct names', () => {
    createWaf({ botControlEnabled: false });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'AWSManagedRulesCommonRuleSet',
          Priority: 1,
          Statement: {
            ManagedRuleGroupStatement: {
              VendorName: 'AWS',
              Name: 'AWSManagedRulesCommonRuleSet',
            },
          },
        }),
        Match.objectLike({
          Name: 'AWSManagedRulesKnownBadInputsRuleSet',
          Priority: 2,
          Statement: {
            ManagedRuleGroupStatement: {
              VendorName: 'AWS',
              Name: 'AWSManagedRulesKnownBadInputsRuleSet',
            },
          },
        }),
        Match.objectLike({
          Name: 'AWSManagedRulesAmazonIpReputationList',
          Priority: 3,
          Statement: {
            ManagedRuleGroupStatement: {
              VendorName: 'AWS',
              Name: 'AWSManagedRulesAmazonIpReputationList',
            },
          },
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
    expect(Object.keys(rules)).toEqual([
      'AWSManagedRulesCommonRuleSet',
      'AWSManagedRulesKnownBadInputsRuleSet',
      'AWSManagedRulesAmazonIpReputationList',
      'AWSManagedRulesBotControlRuleSet',
    ]);
    for (const rule of Object.values(rules)) {
      expect(rule.OverrideAction).toEqual({ Count: {} });
    }
  });

  test('block for one rule group yields OverrideAction None only there', () => {
    createWaf({ managedRuleActions: { ...ALL_COUNT, ipReputation: 'block' } });
    const rules = managedRules();
    expect(rules.AWSManagedRulesAmazonIpReputationList.OverrideAction).toEqual({
      None: {},
    });
    expect(rules.AWSManagedRulesCommonRuleSet.OverrideAction).toEqual({
      Count: {},
    });
    expect(rules.AWSManagedRulesKnownBadInputsRuleSet.OverrideAction).toEqual({
      Count: {},
    });
    expect(rules.AWSManagedRulesBotControlRuleSet.OverrideAction).toEqual({
      Count: {},
    });
  });

  test('rule count override yields RuleActionOverrides with Count', () => {
    createWaf({
      managedRuleActions: { ...ALL_COUNT, common: 'block' },
      ruleCountOverrides: {
        common: ['SizeRestrictions_BODY', 'NoUserAgent_HEADER'],
      },
    });
    const rules = managedRules();
    expect(rules.AWSManagedRulesCommonRuleSet).toMatchObject({
      OverrideAction: { None: {} },
      Statement: {
        ManagedRuleGroupStatement: {
          RuleActionOverrides: [
            { Name: 'SizeRestrictions_BODY', ActionToUse: { Count: {} } },
            { Name: 'NoUserAgent_HEADER', ActionToUse: { Count: {} } },
          ],
        },
      },
    });
  });

  test('no RuleActionOverrides without count overrides', () => {
    createWaf();
    for (const rule of Object.values(managedRules())) {
      const statement = rule.Statement as {
        ManagedRuleGroupStatement: Record<string, unknown>;
      };
      expect(statement.ManagedRuleGroupStatement).not.toHaveProperty(
        'RuleActionOverrides',
      );
    }
  });

  test('unknown rule name in count overrides throws', () => {
    expect(() =>
      createWaf({ ruleCountOverrides: { common: ['SizeRestriction_BODY'] } }),
    ).toThrow(/unknown rule name 'SizeRestriction_BODY'/);
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

  test('Bot Control present when botControlEnabled is true', () => {
    createWaf({ botControlEnabled: true });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'AWSManagedRulesBotControlRuleSet',
          Priority: 4,
          OverrideAction: { Count: {} },
          Statement: {
            ManagedRuleGroupStatement: {
              VendorName: 'AWS',
              Name: 'AWSManagedRulesBotControlRuleSet',
            },
          },
        }),
      ]),
    });
  });

  test('creates WebACLAssociation with correct resource ARN', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACLAssociation', {
      ResourceArn:
        'arn:aws:apigateway:eu-central-1::/restapis/abc123/stages/prod',
    });
  });

  test('exports WebACL ARN as CfnOutput', () => {
    createWaf();
    const template = Template.fromStack(stack);
    const outputs = template.findOutputs('*');
    const wafOutput = Object.entries(outputs).find(([key]) =>
      key.includes('WafWebAclArn'),
    );
    expect(wafOutput).toBeDefined();
    expect(wafOutput![1].Description).toBe('WAF WebACL ARN');
  });

  test('consent rate limit rule scoped to POST /api/consent with 100 req/5min', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'ConsentRateLimitPerIP',
          Priority: 5,
          Action: {
            Block: {
              CustomResponse: {
                ResponseCode: 429,
                CustomResponseBodyKey: 'rate-limit-response',
              },
            },
          },
          Statement: {
            RateBasedStatement: {
              Limit: 100,
              AggregateKeyType: 'FORWARDED_IP',
              ForwardedIPConfig: {
                HeaderName: 'X-Forwarded-For',
                FallbackBehavior: 'MATCH',
              },
              ScopeDownStatement: {
                AndStatement: {
                  Statements: [
                    {
                      ByteMatchStatement: {
                        SearchString: '/api/consent',
                        FieldToMatch: { UriPath: {} },
                        PositionalConstraint: 'STARTS_WITH',
                        TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                      },
                    },
                    {
                      ByteMatchStatement: {
                        SearchString: 'POST',
                        FieldToMatch: { Method: {} },
                        PositionalConstraint: 'EXACTLY',
                        TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                      },
                    },
                  ],
                },
              },
            },
          },
        }),
      ]),
    });
  });

  test('session delete rate limit rule scoped to DELETE /api/session with 100 req/5min', () => {
    createWaf();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::WAFv2::WebACL', {
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: 'SessionDeleteRateLimitPerIP',
          Priority: 6,
          Action: {
            Block: {
              CustomResponse: {
                ResponseCode: 429,
                CustomResponseBodyKey: 'rate-limit-response',
              },
            },
          },
          Statement: {
            RateBasedStatement: {
              Limit: 100,
              AggregateKeyType: 'FORWARDED_IP',
              ForwardedIPConfig: {
                HeaderName: 'X-Forwarded-For',
                FallbackBehavior: 'MATCH',
              },
              ScopeDownStatement: {
                AndStatement: {
                  Statements: [
                    {
                      ByteMatchStatement: {
                        SearchString: '/api/session',
                        FieldToMatch: { UriPath: {} },
                        PositionalConstraint: 'STARTS_WITH',
                        TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                      },
                    },
                    {
                      ByteMatchStatement: {
                        SearchString: 'DELETE',
                        FieldToMatch: { Method: {} },
                        PositionalConstraint: 'EXACTLY',
                        TextTransformations: [{ Priority: 0, Type: 'NONE' }],
                      },
                    },
                  ],
                },
              },
            },
          },
        }),
      ]),
    });
  });
});
