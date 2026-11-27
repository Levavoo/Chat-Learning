import { join } from 'path';
import { bundleCloudFrontFunctionCode } from '../../../lib/constructs/cloudfront-functions/bundle';

describe('bundleCloudFrontFunctionCode', () => {
  const entryPath = join(
    __dirname,
    '../../../lib/constructs/cloudfront-functions/maintenance-mode.function.ts',
  );

  test('does not emit a CommonJS module wrapper', () => {
    const code = bundleCloudFrontFunctionCode(entryPath);

    expect(code).not.toContain('exports.');
    expect(code).not.toContain('Object.defineProperty(exports');
    expect(code).not.toContain('require(');
  });

  test('preserves the ES module import of the cloudfront runtime', () => {
    const code = bundleCloudFrontFunctionCode(entryPath);

    expect(code).toMatch(/from\s+["']cloudfront["']/);
  });

  test('downlevels syntax the CloudFront JS 2.0 runtime cannot parse', () => {
    const code = bundleCloudFrontFunctionCode(entryPath);

    // The runtime is ES 5.1 plus selected ES6–12 features; an optional catch
    // binding (`catch {`, ES2019) is not among them and aborts every
    // invocation with a FunctionExecutionError.
    expect(code).not.toMatch(/catch\s*\{/);
  });

  test('defines a bare top-level handler function without exporting it', () => {
    const code = bundleCloudFrontFunctionCode(entryPath);

    expect(code).toMatch(/(^|\n)(async\s+)?function\s+handler\s*\(/);
    expect(code).not.toMatch(/export/);
  });
});
