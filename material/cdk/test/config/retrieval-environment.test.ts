import { App } from 'aws-cdk-lib';

import { configureProdPhysicalNameContext } from '../../lib/config/retrieval-environment';

describe('#668 — prod physical-name context', () => {
  test('defaults the legacy physical-name context to prod', () => {
    const app = new App({ context: { env: 'prod' } });

    configureProdPhysicalNameContext(app.node, 'prod');

    expect(app.node.tryGetContext('environment')).toBe('prod');
  });

  test('accepts an explicitly aligned prod context', () => {
    const app = new App({
      context: { env: 'prod', environment: 'prod' },
    });

    expect(() =>
      configureProdPhysicalNameContext(app.node, 'prod'),
    ).not.toThrow();
  });

  test('rejects a conflicting physical-name context for prod', () => {
    const app = new App({
      context: { env: 'prod', environment: 'dev' },
    });

    expect(() => configureProdPhysicalNameContext(app.node, 'prod')).toThrow(
      /env=prod requires environment=prod/,
    );
  });

  test('leaves existing non-prod naming behavior unchanged', () => {
    const app = new App({ context: { env: 'preprod' } });

    configureProdPhysicalNameContext(app.node, 'preprod');

    expect(app.node.tryGetContext('environment')).toBeUndefined();
  });
});
