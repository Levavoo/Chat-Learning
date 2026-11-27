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

export interface WafProps {
  readonly prefix: string;
  readonly envName: string;
  /** Requests per 5 min per IP. */
  readonly rateLimitPerIp: number;
  readonly botControlEnabled: boolean;
  /** Action per managed rule group on this Web ACL. */
  readonly managedRuleActions: WafRuleGroupActions;
  /** Rules kept on `count` inside a rule group. */
  readonly ruleCountOverrides?: WafRuleGroupCountOverrides;
  readonly apiGatewayStageArn: string;
}

export class WafConstruct extends Construct {
  public readonly webAcl: wafv2.CfnWebACL;
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: WafProps) {
    super(scope, id);

    const metricBase = `${props.prefix}-waf`;

    // Priorities 0, 5, 6; managed rule groups take 1-4.
    const rateRules: RateRuleSpec[] = [
      {
        name: 'RateLimitPerIP',
        priority: 0,
        limit: props.rateLimitPerIp,
        aggregateKeyType: 'FORWARDED_IP',
        pathPrefix: '/api/chat',
        metricName: `${metricBase}-rate-limit-${props.envName}`,
      },
      // POST /api/consent: 100/5min per IP.
      {
        name: 'ConsentRateLimitPerIP',
        priority: 5,
        limit: 100,
        aggregateKeyType: 'FORWARDED_IP',
        pathPrefix: '/api/consent',
        method: 'POST',
        metricName: `${metricBase}-consent-rate-limit-${props.envName}`,
      },
      // DELETE /api/session: 100 is the WAF minimum, combined with UUIDv4 entropy
      // this blocks enumeration (legitimate users delete at most one session).
      {
        name: 'SessionDeleteRateLimitPerIP',
        priority: 6,
        limit: 100,
        aggregateKeyType: 'FORWARDED_IP',
        pathPrefix: '/api/session',
        method: 'DELETE',
        metricName: `${metricBase}-session-delete-rate-limit-${props.envName}`,
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
      scope: 'REGIONAL',
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

    new wafv2.CfnWebACLAssociation(this, 'WebAclAssociation', {
      webAclArn: this.webAcl.attrArn,
      resourceArn: props.apiGatewayStageArn,
    });

    new CfnOutput(this, 'WafWebAclArn', {
      value: this.webAcl.attrArn,
      description: 'WAF WebACL ARN',
      exportName: `${props.envName}-WafWebAclArn`,
    });
  }
}
