import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import {
  MANAGED_RULE_GROUPS,
  WAF_RULE_GROUPS,
  WafRuleGroup,
  WafRuleGroupActions,
  WafRuleGroupCountOverrides,
  findInvalidGroupCountOverrides,
} from '../config/waf-managed-rules';

/**
 * Builds Web ACL rules from plain data (#988). Both Web ACLs describe their
 * rules as lists and share these builders, so a later move to OpenTofu is a
 * translation of the lists.
 */

export interface RateRuleSpec {
  readonly name: string;
  readonly priority: number;
  /** Requests per 5 min per key. */
  readonly limit: number;
  readonly aggregateKeyType: 'IP' | 'FORWARDED_IP';
  /** URI path prefix the rule applies to. */
  readonly pathPrefix?: string;
  /** HTTP method the rule applies to. */
  readonly method?: string;
  readonly metricName: string;
}

const byteMatch = (
  searchString: string,
  fieldToMatch: wafv2.CfnWebACL.FieldToMatchProperty,
  positionalConstraint: 'EXACTLY' | 'STARTS_WITH',
): wafv2.CfnWebACL.StatementProperty => ({
  byteMatchStatement: {
    searchString,
    fieldToMatch,
    positionalConstraint,
    textTransformations: [{ priority: 0, type: 'NONE' }],
  },
});

const visibility = (
  metricName: string,
): wafv2.CfnWebACL.VisibilityConfigProperty => ({
  cloudWatchMetricsEnabled: true,
  metricName,
  sampledRequestsEnabled: true,
});

export const RATE_LIMIT_RESPONSE_BODY_KEY = 'rate-limit-response';

export const RATE_LIMIT_RESPONSE_BODIES: Record<
  string,
  wafv2.CfnWebACL.CustomResponseBodyProperty
> = {
  [RATE_LIMIT_RESPONSE_BODY_KEY]: {
    contentType: 'APPLICATION_JSON',
    content: JSON.stringify({
      error: 'rate_limit_exceeded',
      message:
        'Zu viele Anfragen. Bitte versuchen Sie es in einigen Minuten erneut.',
    }),
  },
};

/** Rate rules always block with HTTP 429. */
export function buildRateRule(
  spec: RateRuleSpec,
): wafv2.CfnWebACL.RuleProperty {
  const conditions: wafv2.CfnWebACL.StatementProperty[] = [];
  if (spec.pathPrefix) {
    conditions.push(byteMatch(spec.pathPrefix, { uriPath: {} }, 'STARTS_WITH'));
  }
  if (spec.method) {
    conditions.push(byteMatch(spec.method, { method: {} }, 'EXACTLY'));
  }
  if (conditions.length === 0) {
    throw new Error(`Rate rule ${spec.name} needs pathPrefix or method`);
  }
  const scopeDownStatement =
    conditions.length === 1
      ? conditions[0]
      : { andStatement: { statements: conditions } };

  return {
    name: spec.name,
    priority: spec.priority,
    action: {
      block: {
        customResponse: {
          responseCode: 429,
          customResponseBodyKey: RATE_LIMIT_RESPONSE_BODY_KEY,
        },
      },
    },
    statement: {
      rateBasedStatement: {
        limit: spec.limit,
        aggregateKeyType: spec.aggregateKeyType,
        ...(spec.aggregateKeyType === 'FORWARDED_IP' && {
          forwardedIpConfig: {
            headerName: 'X-Forwarded-For',
            fallbackBehavior: 'MATCH',
          },
        }),
        scopeDownStatement,
      },
    },
    visibilityConfig: visibility(spec.metricName),
  };
}

export interface ManagedRuleGroupsSpec {
  readonly actions: WafRuleGroupActions;
  readonly countOverrides?: WafRuleGroupCountOverrides;
  readonly botControlEnabled: boolean;
  /** e.g. `renate-waf` or `renate-cf-waf`; metric = `<base>-<suffix>-<env>`. */
  readonly metricBase: string;
  readonly envName: string;
}

/** Managed rule groups in fixed order and priority (1-4). */
export function buildManagedRuleGroupRules(
  spec: ManagedRuleGroupsSpec,
): wafv2.CfnWebACL.RuleProperty[] {
  const problems = findInvalidGroupCountOverrides(
    spec.countOverrides,
    spec.metricBase,
  );
  if (problems.length > 0) {
    throw new Error(`Invalid WAF rule count overrides: ${problems.join('; ')}`);
  }

  const groups: WafRuleGroup[] = WAF_RULE_GROUPS.filter(
    (g) => g !== 'botControl' || spec.botControlEnabled,
  );

  return groups.map((group) => {
    const def = MANAGED_RULE_GROUPS[group];
    const overrides = spec.countOverrides?.[group] ?? [];
    return {
      name: def.awsName,
      priority: def.priority,
      overrideAction:
        spec.actions[group] === 'block' ? { none: {} } : { count: {} },
      statement: {
        managedRuleGroupStatement: {
          vendorName: 'AWS',
          name: def.awsName,
          ...(overrides.length > 0 && {
            ruleActionOverrides: overrides.map((name) => ({
              name,
              actionToUse: { count: {} },
            })),
          }),
        },
      },
      visibilityConfig: visibility(
        `${spec.metricBase}-${def.metricSuffix}-${spec.envName}`,
      ),
    };
  });
}
