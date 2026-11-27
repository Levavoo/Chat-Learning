import { Construct } from 'constructs';
import { CfnOutput } from 'aws-cdk-lib';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import {
  WafRuleGroupActions,
  WafRuleGroupCountOverrides,
} from '../config/waf-managed-rules';
import {
  RATE_LIMIT_RESPONSE_BODIES,
  RateRuleSpec,
  buildManagedRuleGroupRules,
  buildRateRule,
} from './waf-rules';

export interface CloudFrontWafProps {
  readonly prefix: string;
  readonly envName: string;
  /** Requests per 5 min per IP. */
  readonly rateLimitPerIp: number;
  readonly botControlEnabled: boolean;
  /** Action per managed rule group on this Web ACL. */
  readonly managedRuleActions: WafRuleGroupActions;
  /** Rules kept on `count` inside a rule group. */
  readonly ruleCountOverrides?: WafRuleGroupCountOverrides;
}

export class CloudFrontWafConstruct extends Construct {
  public readonly webAcl: wafv2.CfnWebACL;
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: CloudFrontWafProps) {
    super(scope, id);

    const metricBase = `${props.prefix}-cf-waf`;

    // Priority 0; managed rule groups take 1-4.
    const rateRules: RateRuleSpec[] = [
      // POST-scoped rate limit covers the API origin only.
      {
        name: 'RateLimitPerIP',
        priority: 0,
        limit: props.rateLimitPerIp,
        aggregateKeyType: 'IP',
        method: 'POST',
        metricName: `${metricBase}-rate-limit-${props.envName}`,
      },
    ];

    // Sorted by priority, which is also the order the template had before.
    const rules: wafv2.CfnWebACL.RuleProperty[] = [
      ...rateRules.map(buildRateRule),
      ...buildManagedRuleGroupRules({
        actions: props.managedRuleActions,
        countOverrides: props.ruleCountOverrides,
        botControlEnabled: props.botControlEnabled,
        metricBase,
        envName: props.envName,
      }),
    ].sort((a, b) => a.priority - b.priority);

    this.webAcl = new wafv2.CfnWebACL(this, 'WebAcl', {
      name: `${metricBase}-${props.envName}`,
      scope: 'CLOUDFRONT',
      defaultAction: { allow: {} },
      rules: rules,
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: `${metricBase}-${props.envName}`,
        sampledRequestsEnabled: true,
      },
      customResponseBodies: RATE_LIMIT_RESPONSE_BODIES,
    });

    this.webAclArn = this.webAcl.attrArn;

    new CfnOutput(this, 'CloudFrontWafWebAclArn', {
      value: this.webAcl.attrArn,
      description: 'CloudFront WAF WebACL ARN',
    });
  }
}
