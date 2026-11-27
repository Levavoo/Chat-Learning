import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { getChatbotParameters } from '../../lib/utils/parameter-models';
import { chatbotParametersMap } from '../../parameter';
import { loadEnvConfig } from '../../lib/utils/env-config';

const minRequired = {
  envName: 'test',
  account: '123456789012',
  chatbotStackName: 'test-stack',
  prefix: 'test',
  frontendOrigin: 'https://test.example.com',
  userPoolDomainPrefix: 'test-auth',
};

function makeApp(context: Record<string, unknown> = {}): cdk.App {
  return new cdk.App({ context });
}

describe('getChatbotParameters — zBoolContext coercion', () => {
  test('accepts native boolean true', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired, anonymousAccess: true }]]),
    );
    expect(params.anonymousAccess).toBe(true);
  });

  test('accepts native boolean false', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired, anonymousAccess: false }]]),
    );
    expect(params.anonymousAccess).toBe(false);
  });

  test('coerces string "false" from CDK context to boolean false', () => {
    const app = makeApp({ anonymousAccess: 'false' });
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.anonymousAccess).toBe(false);
  });

  test('coerces string "true" from CDK context to boolean true', () => {
    const app = makeApp({ anonymousAccess: 'true' });
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.anonymousAccess).toBe(true);
  });

  test('defaults to false when not set', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.anonymousAccess).toBe(false);
  });

  test('throws on unrecognized boolean context value', () => {
    const app = makeApp({ anonymousAccess: 'yes' });
    expect(() =>
      getChatbotParameters(
        app,
        'test',
        new Map([['test', { ...minRequired }]]),
      ),
    ).toThrow();
  });
});

describe('getChatbotParameters — overrides (config.yaml highest priority)', () => {
  test('overrides wins over parameter map value', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired, anonymousAccess: false }]]),
      { anonymousAccess: true },
    );
    expect(params.anonymousAccess).toBe(true);
  });

  test('overrides wins over CDK context', () => {
    const app = makeApp({ anonymousAccess: 'false' });
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
      { anonymousAccess: true },
    );
    expect(params.anonymousAccess).toBe(true);
  });

  test('empty overrides does not change defaults', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
      {},
    );
    expect(params.anonymousAccess).toBe(false);
  });
});

describe('getChatbotParameters — geoRestrictionCountries (#616)', () => {
  test('defaults to empty array when unset', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.geoRestrictionCountries).toEqual([]);
  });

  test('accepts DACH allowlist from parameter map', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([
        [
          'test',
          { ...minRequired, geoRestrictionCountries: ['DE', 'AT', 'CH'] },
        ],
      ]),
    );
    expect(params.geoRestrictionCountries).toEqual(['DE', 'AT', 'CH']);
  });

  test('rejects lowercase ISO codes', () => {
    const app = makeApp();
    expect(() =>
      getChatbotParameters(
        app,
        'test',
        new Map([
          ['test', { ...minRequired, geoRestrictionCountries: ['de'] }],
        ]),
      ),
    ).toThrow(/ISO 3166-1 alpha-2/);
  });

  test('rejects non-2-char codes', () => {
    const app = makeApp();
    expect(() =>
      getChatbotParameters(
        app,
        'test',
        new Map([
          ['test', { ...minRequired, geoRestrictionCountries: ['DEU'] }],
        ]),
      ),
    ).toThrow();
  });
});

describe('loadEnvConfig → getChatbotParameters integration', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'param-integration-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true });
  });

  test('config.yaml true overrides parameter map false end-to-end', () => {
    const dir = path.join(tmpDir, 'deployments', 'dev');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'config.yaml'), 'anonymousAccess: true\n');

    const envConfig = loadEnvConfig(tmpDir, 'dev');
    const app = new cdk.App();
    const params = getChatbotParameters(
      app,
      'dev',
      new Map([['dev', { ...minRequired, anonymousAccess: false }]]),
      envConfig,
    );
    expect(params.anonymousAccess).toBe(true);
  });

  test('missing config.yaml leaves parameter map value unchanged', () => {
    const envConfig = loadEnvConfig(tmpDir, 'dev');
    const app = new cdk.App();
    const params = getChatbotParameters(
      app,
      'dev',
      new Map([['dev', { ...minRequired, anonymousAccess: false }]]),
      envConfig,
    );
    expect(params.anonymousAccess).toBe(false);
  });
});

describe('getChatbotParameters — frontendDnsRecordName', () => {
  test('accepts valid FQDN for frontendDnsRecordName', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([
        [
          'test',
          {
            ...minRequired,
            frontendDnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
          },
        ],
      ]),
    );
    expect(params.frontendDnsRecordName).toBe(
      'rentenchat.deutsche-rentenversicherung.de',
    );
  });

  test('defaults to undefined when not set', () => {
    const app = makeApp();
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.frontendDnsRecordName).toBeUndefined();
  });

  test('rejects empty string', () => {
    const app = makeApp();
    expect(() =>
      getChatbotParameters(
        app,
        'test',
        new Map([['test', { ...minRequired, frontendDnsRecordName: '' }]]),
      ),
    ).toThrow();
  });

  test('resolves from CDK context', () => {
    const app = makeApp({ frontendDnsRecordName: 'example.com' });
    const params = getChatbotParameters(
      app,
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.frontendDnsRecordName).toBe('example.com');
  });
});

describe('getChatbotParameters — langfuseKeyRotatedAt (#979)', () => {
  test('accepts a valid UTC timestamp from the parameter map', () => {
    const params = getChatbotParameters(
      makeApp(),
      'test',
      new Map([
        ['test', { ...minRequired, langfuseKeyRotatedAt: '2026-11-16T22:30Z' }],
      ]),
    );
    expect(params.langfuseKeyRotatedAt).toBe('2026-11-16T22:30Z');
  });

  test('reads the value from CDK context', () => {
    const params = getChatbotParameters(
      makeApp({ langfuseKeyRotatedAt: '2026-11-16T22:30Z' }),
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.langfuseKeyRotatedAt).toBe('2026-11-16T22:30Z');
  });

  test('stays undefined when not set', () => {
    const params = getChatbotParameters(
      makeApp(),
      'test',
      new Map([['test', { ...minRequired }]]),
    );
    expect(params.langfuseKeyRotatedAt).toBeUndefined();
  });

  test.each([
    '2026-11-16',
    '16.11.2026 22:30',
    '2026-11-16T22:30:00Z',
    '2026-11-16T22:30',
    '2026-11-16T22:30+01:00',
    '2026-13-01T10:00Z',
    '2026-02-30T10:00Z',
    '2026-11-16T24:00Z',
    '2026-11-16T22:60Z',
    '',
  ])('rejects %p', (value) => {
    expect(() =>
      getChatbotParameters(
        makeApp(),
        'test',
        new Map([['test', { ...minRequired, langfuseKeyRotatedAt: value }]]),
      ),
    ).toThrow(/langfuseKeyRotatedAt/);
  });
});

describe('getChatbotParameters — WAF actions per rule group (#988)', () => {
  const params = (
    extra: Record<string, unknown> = {},
    context: Record<string, unknown> = {},
  ) =>
    getChatbotParameters(
      makeApp(context),
      'test',
      new Map([['test', { ...minRequired, ...extra }]]),
    );

  const allCount = {
    common: 'count',
    knownBadInputs: 'count',
    ipReputation: 'count',
    botControl: 'count',
  };

  test('defaults every Web ACL and rule group to count', () => {
    const p = params();
    expect(p.wafManagedRuleActions).toEqual({
      cloudfront: allCount,
      regional: allCount,
    });
    expect(p.wafRuleCountOverrides).toEqual({});
  });

  test('omitted entries stay on count', () => {
    const p = params({
      wafManagedRuleActions: { regional: { ipReputation: 'block' } },
    });
    expect(p.wafManagedRuleActions).toEqual({
      cloudfront: allCount,
      regional: { ...allCount, ipReputation: 'block' },
    });
  });

  test('rejects --context, which parameter.ts would silently override', () => {
    expect(() =>
      params(
        {},
        { wafManagedRuleActions: '{"regional":{"ipReputation":"block"}}' },
      ),
    ).toThrow(/wafManagedRuleActions can only be set in cdk\/parameter.ts/);
    expect(() =>
      params(
        {},
        {
          wafRuleCountOverrides:
            '{"cloudfront":{"common":["SizeRestrictions_BODY"]}}',
        },
      ),
    ).toThrow(/wafRuleCountOverrides can only be set in cdk\/parameter.ts/);
  });

  test('rejects --context with the real prod parameter map', () => {
    // The real map sets wafManagedRuleActions for prod, so a context value
    // would otherwise be dropped without notice.
    expect(
      chatbotParametersMap.get('prod')?.wafManagedRuleActions,
    ).toBeDefined();
    expect(() =>
      getChatbotParameters(
        makeApp({
          wafManagedRuleActions: '{"regional":{"ipReputation":"block"}}',
        }),
        'prod',
        chatbotParametersMap,
      ),
    ).toThrow(/can only be set in cdk\/parameter.ts/);
  });

  test('rejects config.yaml overrides, which would silently win', () => {
    expect(() =>
      getChatbotParameters(
        makeApp(),
        'test',
        new Map([['test', { ...minRequired }]]),
        { wafManagedRuleActions: { regional: { common: 'count' } } },
      ),
    ).toThrow(/can only be set in cdk\/parameter.ts/);
  });

  test('real parameter map keeps every environment on count', () => {
    for (const env of ['dev', 'qa', 'demo', 'preprod', 'prod']) {
      const p = getChatbotParameters(makeApp(), env, chatbotParametersMap);
      expect(p.wafManagedRuleActions).toEqual({
        cloudfront: allCount,
        regional: allCount,
      });
      expect(p.wafRuleCountOverrides).toEqual({});
    }
  });

  test('rejects an unknown action', () => {
    expect(() =>
      params({ wafManagedRuleActions: { regional: { common: 'allow' } } }),
    ).toThrow(/wafManagedRuleActions/);
  });

  test('rejects an unknown rule group key', () => {
    expect(() =>
      params({
        wafManagedRuleActions: { regional: { commonRuleSet: 'block' } },
      }),
    ).toThrow(/wafManagedRuleActions/);
  });

  test('accepts known rule names in count overrides', () => {
    const p = params({
      wafRuleCountOverrides: {
        regional: { knownBadInputs: ['Log4JRCE_BODY'] },
      },
    });
    expect(p.wafRuleCountOverrides.regional?.knownBadInputs).toEqual([
      'Log4JRCE_BODY',
    ]);
  });

  test('unknown rule name fails (synth aborts)', () => {
    expect(() =>
      params({
        wafRuleCountOverrides: {
          cloudfront: { common: ['SizeRestriction_BODY'] },
        },
      }),
    ).toThrow(/cloudfront\.common: unknown rule name 'SizeRestriction_BODY'/);
  });

  test('duplicate rule name fails', () => {
    expect(() =>
      params({
        wafRuleCountOverrides: {
          regional: {
            ipReputation: ['AWSManagedIPDDoSList', 'AWSManagedIPDDoSList'],
          },
        },
      }),
    ).toThrow(/duplicate rule name 'AWSManagedIPDDoSList'/);
  });

  test('wafRuleAction is no longer part of the parameters', () => {
    expect(params()).not.toHaveProperty('wafRuleAction');
  });

  test('a leftover wafRuleAction fails instead of being ignored', () => {
    expect(() => params({}, { wafRuleAction: 'block' })).toThrow(
      /wafRuleAction was removed/,
    );
    expect(() => params({ wafRuleAction: 'block' })).toThrow(
      /wafRuleAction was removed/,
    );
  });
});
