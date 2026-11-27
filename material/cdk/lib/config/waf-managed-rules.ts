/**
 * AWS Managed Rule Groups used by both Web ACLs (#988, ADR-003 Maßnahme 1).
 *
 * The action is set per Web ACL and per rule group, so a single rule group
 * can be enforced while the others stay on `count`. Single rules inside a
 * group can be kept on `count` via RuleActionOverrides.
 */

export const WAF_WEB_ACLS = ['cloudfront', 'regional'] as const;
export type WafWebAcl = (typeof WAF_WEB_ACLS)[number];

export const WAF_RULE_GROUPS = [
  'common',
  'knownBadInputs',
  'ipReputation',
  'botControl',
] as const;
export type WafRuleGroup = (typeof WAF_RULE_GROUPS)[number];

/** `count` = OverrideAction Count (log only), `block` = OverrideAction None (rule group's own actions apply). */
export type WafManagedRuleAction = 'count' | 'block';

export type WafRuleGroupActions = Record<WafRuleGroup, WafManagedRuleAction>;
export type WafManagedRuleActions = Record<WafWebAcl, WafRuleGroupActions>;

/** Rule names per rule group that stay on `count` although the group blocks. */
export type WafRuleGroupCountOverrides = Partial<
  Record<WafRuleGroup, readonly string[]>
>;
export type WafRuleCountOverrides = Partial<
  Record<WafWebAcl, WafRuleGroupCountOverrides>
>;

export interface ManagedRuleGroupDefinition {
  /** AWS rule group name, also used as rule name in the Web ACL. */
  readonly awsName: string;
  readonly priority: number;
  /** Middle part of the CloudWatch metric name. */
  readonly metricSuffix: string;
  /**
   * Rule names of the current default version of the rule group. AWS WAF
   * ignores unknown names in RuleActionOverrides silently, so this list is
   * the only typo guard: `wafRuleCountOverrides` is checked against it at
   * synth time. The rule groups are not version-pinned, so AWS can change
   * the rules. Before a rule group is set to `block`, compare this list with
   * `aws wafv2 describe-managed-rule-group` (last checked 2026-11-20, prod).
   */
  readonly ruleNames: readonly string[];
}

export const MANAGED_RULE_GROUPS: Record<
  WafRuleGroup,
  ManagedRuleGroupDefinition
> = {
  common: {
    awsName: 'AWSManagedRulesCommonRuleSet',
    priority: 1,
    metricSuffix: 'common',
    ruleNames: [
      'NoUserAgent_HEADER',
      'UserAgent_BadBots_HEADER',
      'SizeRestrictions_QUERYSTRING',
      'SizeRestrictions_Cookie_HEADER',
      'SizeRestrictions_BODY',
      'SizeRestrictions_URIPATH',
      'EC2MetaDataSSRF_BODY',
      'EC2MetaDataSSRF_COOKIE',
      'EC2MetaDataSSRF_URIPATH',
      'EC2MetaDataSSRF_QUERYARGUMENTS',
      'GenericLFI_QUERYARGUMENTS',
      'GenericLFI_URIPATH',
      'GenericLFI_BODY',
      'RestrictedExtensions_URIPATH',
      'RestrictedExtensions_QUERYARGUMENTS',
      'GenericRFI_QUERYARGUMENTS',
      'GenericRFI_BODY',
      'GenericRFI_URIPATH',
      'CrossSiteScripting_COOKIE',
      'CrossSiteScripting_QUERYARGUMENTS',
      'CrossSiteScripting_BODY',
      'CrossSiteScripting_URIPATH',
    ],
  },
  knownBadInputs: {
    awsName: 'AWSManagedRulesKnownBadInputsRuleSet',
    priority: 2,
    metricSuffix: 'bad-inputs',
    ruleNames: [
      'JavaDeserializationRCE_HEADER',
      'JavaDeserializationRCE_BODY',
      'JavaDeserializationRCE_URIPATH',
      'JavaDeserializationRCE_QUERYSTRING',
      'Host_localhost_HEADER',
      'PROPFIND_METHOD',
      'ExploitablePaths_URIPATH',
      'Log4JRCE_HEADER',
      'Log4JRCE_QUERYSTRING',
      'Log4JRCE_BODY',
      'Log4JRCE_URIPATH',
      'ReactJSRCE_BODY',
    ],
  },
  ipReputation: {
    awsName: 'AWSManagedRulesAmazonIpReputationList',
    priority: 3,
    metricSuffix: 'ip-reputation',
    ruleNames: [
      'AWSManagedIPReputationList',
      'AWSManagedReconnaissanceList',
      'AWSManagedIPDDoSList',
    ],
  },
  // Inspection level COMMON (no ManagedRuleGroupConfigs set). The TGT_* rules
  // exist only at inspection level TARGETED and are left out on purpose.
  botControl: {
    awsName: 'AWSManagedRulesBotControlRuleSet',
    priority: 4,
    metricSuffix: 'bot-control',
    ruleNames: [
      'CategoryAdvertising',
      'CategoryArchiver',
      'CategoryContentFetcher',
      'CategoryEmailClient',
      'CategoryHttpLibrary',
      'CategoryLinkChecker',
      'CategoryMiscellaneous',
      'CategoryMonitoring',
      'CategoryScrapingFramework',
      'CategorySearchEngine',
      'CategorySecurity',
      'CategorySeo',
      'CategorySocialMedia',
      'CategoryAI',
      'SignalAutomatedBrowser',
      'SignalKnownBotDataCenter',
      'SignalNonBrowserUserAgent',
    ],
  },
};

const allCount = (): WafRuleGroupActions => ({
  common: 'count',
  knownBadInputs: 'count',
  ipReputation: 'count',
  botControl: 'count',
});

export const DEFAULT_WAF_MANAGED_RULE_ACTIONS: WafManagedRuleActions = {
  cloudfront: allCount(),
  regional: allCount(),
};

/**
 * Returns one message per unknown or duplicate rule name. Empty = valid.
 * Called from the parameter schema (synth fails) and from the constructs.
 */
export function findInvalidRuleCountOverrides(
  overrides: WafRuleCountOverrides | undefined,
): string[] {
  return WAF_WEB_ACLS.flatMap((webAcl) =>
    findInvalidGroupCountOverrides(overrides?.[webAcl], webAcl),
  );
}

/** Same check for the overrides of one Web ACL; `label` prefixes messages. */
export function findInvalidGroupCountOverrides(
  perGroup: WafRuleGroupCountOverrides | undefined,
  label: string,
): string[] {
  const problems: string[] = [];
  for (const group of WAF_RULE_GROUPS) {
    const names = perGroup?.[group];
    if (!names) continue;
    const def = MANAGED_RULE_GROUPS[group];
    const seen = new Set<string>();
    for (const name of names) {
      if (!def.ruleNames.includes(name)) {
        problems.push(
          `${label}.${group}: unknown rule name '${name}' in ${def.awsName}`,
        );
      }
      if (seen.has(name)) {
        problems.push(`${label}.${group}: duplicate rule name '${name}'`);
      }
      seen.add(name);
    }
  }
  return problems;
}
