import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'js-yaml';

/**
 * Loads per-environment feature flags from deployments/<env>/config.yaml.
 *
 * The file is optional — if absent, an empty object is returned and all
 * flags fall back to their Zod schema defaults. Values must be booleans;
 * see docs/runbooks/feature_flags_config_yaml.md for the full key reference.
 */
export function loadEnvConfig(
  repoRoot: string,
  envName: string,
): Record<string, unknown> {
  const configPath = path.join(repoRoot, 'deployments', envName, 'config.yaml');

  if (!fs.existsSync(configPath)) {
    return {};
  }

  const raw = yaml.load(fs.readFileSync(configPath, 'utf8'));

  if (raw === null || raw === undefined) {
    return {};
  }

  if (typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(
      `deployments/${envName}/config.yaml must be a YAML mapping, got: ${typeof raw}`,
    );
  }

  return raw as Record<string, unknown>;
}
