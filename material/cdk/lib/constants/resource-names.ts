import * as crypto from 'crypto';

import * as cdk from 'aws-cdk-lib';

const NAME_TEMPLATE: string = '{prefix}-{type}-{purpose}-{env}-{suffix}';

function getResourceTypeName(cfnResourceTypeName: string): string {
  const parts = cfnResourceTypeName.split('::');
  return parts.length === 3
    ? (parts[1]?.toLowerCase() ?? 'unknown')
    : cfnResourceTypeName.toLowerCase();
}

export function deterministicName(
  stack: cdk.Stack,
  cfnResourceTypeName: string,
  purpose: string,
  environmentOverride?: string,
): string {
  const env =
    environmentOverride || stack.node.tryGetContext('environment') || 'dev';
  const project = stack.node.tryGetContext('project') || 'renate';

  // Hash resolved values — stack.stackId is a CFN token at synth, so slicing
  // it produced suffixes that drifted as the construct tree changed.
  const hashInput = `${stack.account}:${stack.region}:${stack.stackName}:${purpose}`;
  const suffix = crypto
    .createHash('sha256')
    .update(hashInput)
    .digest('hex')
    .slice(0, 8);

  const name = NAME_TEMPLATE.replace('{prefix}', project)
    .replace('{type}', getResourceTypeName(cfnResourceTypeName))
    .replace('{purpose}', purpose)
    .replace('{env}', env)
    .replace('{suffix}', suffix);

  const resourceType = getResourceTypeName(cfnResourceTypeName);
  if (resourceType === 's3' && name.length > 63) {
    throw new Error(
      `S3 bucket name exceeds 63 characters: ${name} (${name.length} chars). ` +
        `Consider shortening the purpose or project name.`,
    );
  }

  return name;
}
