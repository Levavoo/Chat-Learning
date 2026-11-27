import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { loadEnvConfig } from '../../lib/utils/env-config';

describe('loadEnvConfig', () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'env-config-test-'));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true });
  });

  const writeConfig = (env: string, content: string) => {
    const dir = path.join(tmpDir, 'deployments', env);
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'config.yaml'), content);
  };

  test('returns empty object when config.yaml does not exist', () => {
    expect(loadEnvConfig(tmpDir, 'dev')).toEqual({});
  });

  test('loads boolean flags from config.yaml', () => {
    writeConfig('dev', 'anonymousAccess: true\n');
    expect(loadEnvConfig(tmpDir, 'dev')).toEqual({ anonymousAccess: true });
  });

  test('loads multiple flags', () => {
    writeConfig('qa', 'anonymousAccess: true\nwafEnabled: true\n');
    expect(loadEnvConfig(tmpDir, 'qa')).toEqual({ anonymousAccess: true, wafEnabled: true });
  });

  test('returns empty object for empty config.yaml', () => {
    writeConfig('dev', '');
    expect(loadEnvConfig(tmpDir, 'dev')).toEqual({});
  });

  test('throws when config.yaml is a list instead of a mapping', () => {
    writeConfig('dev', '- foo\n- bar\n');
    expect(() => loadEnvConfig(tmpDir, 'dev')).toThrow(/must be a YAML mapping/);
  });

  test('ignores comments in config.yaml', () => {
    writeConfig('dev', '# a comment\nanonymousAccess: true\n');
    expect(loadEnvConfig(tmpDir, 'dev')).toEqual({ anonymousAccess: true });
  });
});
