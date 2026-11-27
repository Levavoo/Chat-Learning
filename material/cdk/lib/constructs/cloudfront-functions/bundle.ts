import { buildSync } from 'esbuild';

/**
 * CloudFront JS 2.0 has no CJS globals, only built-in modules like 'cloudfront'.
 * The project's NodeNext tsc emits a CJS wrapper that throws at runtime, so
 * bundle this entry to ESM directly and keep CloudFront modules external.
 *
 * The runtime also rejects `export` statements — it wants a bare top-level
 * `handler`. `format: 'esm'` is still needed so esbuild tree-shaking does not
 * drop the handler; the trailing `export { handler };` is stripped below.
 *
 * `target: 'es2018'` keeps async/await (ES2017) but strips ES2019+ syntax like
 * optional catch binding — those pass deploy-time validation but fail at
 * invoke with FunctionExecutionError.
 */
export function bundleCloudFrontFunctionCode(entryPath: string): string {
  const result = buildSync({
    entryPoints: [entryPath],
    bundle: true,
    write: false,
    format: 'esm',
    target: 'es2018',
    platform: 'neutral',
    external: ['cloudfront', 'crypto', 'querystring', 'uuid'],
  });
  return result.outputFiles[0].text.replace(
    /\nexport\s*\{\s*handler\s*\};?\s*$/,
    '\n',
  );
}
