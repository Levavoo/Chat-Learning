jest.setTimeout(30000);

// Suppress CDK-internal DynamoDB TableGrants deprecation warnings.
// TableV2 sets encryptedResource/policyResource internally — fixing needs a CDK
// version bump (TKT-CI-TD-09).
const originalWarn = console.warn.bind(console);
console.warn = (...args: unknown[]) => {
const msg = args.map(a => String(a ?? '')).join(' ');
  if (
    msg.includes('TableGrantsProps#encryptedResource') ||
    msg.includes('TableGrantsProps#policyResource')
  ) {
    return;
  }
  originalWarn(...args);
};
