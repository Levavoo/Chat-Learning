export type ManifestManagedEnvironment = 'qa' | 'preprod' | 'prod';

interface ContextNode {
  tryGetContext(key: string): unknown;
  setContext(key: string, value: unknown): void;
}

const MANIFEST_MANAGED_ENVIRONMENTS = new Set<string>([
  'qa',
  'preprod',
  'prod',
]);

/**
 * Exhaustive map (not a ternary) so every manifest-managed env must declare
 * its label at compile time — a defaulted label would bind RetrievalHealthAlarms
 * to a namespace the env's health check never publishes to (#668).
 */
const RETRIEVAL_METRIC_LABEL: Record<ManifestManagedEnvironment, string> = {
  qa: 'QA',
  preprod: 'Preprod',
  prod: 'Prod',
};

export function isManifestManagedEnvironment(
  environment: string,
): environment is ManifestManagedEnvironment {
  return MANIFEST_MANAGED_ENVIRONMENTS.has(environment);
}

export function retrievalMetricNamespace(
  environment: ManifestManagedEnvironment,
): string {
  return `Renate/${RETRIEVAL_METRIC_LABEL[environment]}/Retrieval`;
}

/**
 * Normalize prod only — physical naming still reads legacy `environment` and
 * non-prod relies on that historical default. Prod must never silently
 * synthesize `*-dev-*` replacement resources when the legacy context is omitted (#668).
 */
export function configureProdPhysicalNameContext(
  node: ContextNode,
  deploymentEnvironment: string,
): void {
  if (deploymentEnvironment !== 'prod') {
    return;
  }

  const physicalNameEnvironment = node.tryGetContext('environment');
  if (physicalNameEnvironment === undefined) {
    node.setContext('environment', 'prod');
    return;
  }

  if (physicalNameEnvironment !== 'prod') {
    throw new Error(
      `Conflicting CDK contexts: env=prod requires environment=prod, got environment=${String(
        physicalNameEnvironment,
      )}.`,
    );
  }
}
