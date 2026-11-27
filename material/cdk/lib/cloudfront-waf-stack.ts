import { Stack, StackProps } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { CloudFrontWafConstruct } from './constructs/waf-cloudfront';
import {
  WafRuleGroupActions,
  WafRuleGroupCountOverrides,
} from './config/waf-managed-rules';

export interface CloudFrontWafStackProps extends StackProps {
  readonly prefix: string;
  readonly envName: string;
  /** Requests per 5 min per source IP. */
  readonly rateLimitPerIp: number;
  readonly botControlEnabled: boolean;
  /** `wafManagedRuleActions.cloudfront` */
  readonly managedRuleActions: WafRuleGroupActions;
  /** `wafRuleCountOverrides.cloudfront` */
  readonly ruleCountOverrides?: WafRuleGroupCountOverrides;
}

/**
 * Must be deployed to us-east-1 — CLOUDFRONT-scoped WebACLs require it.
 * ARN crosses to ChatbotStack via CDK crossRegionReferences.
 */
export class CloudFrontWafStack extends Stack {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: CloudFrontWafStackProps) {
    super(scope, id, props);

    const waf = new CloudFrontWafConstruct(this, 'CloudFrontWaf', {
      prefix: props.prefix,
      envName: props.envName,
      rateLimitPerIp: props.rateLimitPerIp,
      botControlEnabled: props.botControlEnabled,
      managedRuleActions: props.managedRuleActions,
      ruleCountOverrides: props.ruleCountOverrides,
    });

    this.webAclArn = waf.webAclArn;
  }
}
