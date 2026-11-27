#!/usr/bin/env node
// @ts-check

/**
 * @typedef {'qa'|'preprod'|'prod'} ManifestManagedEnvironment
 * @typedef {{
 *   environment: ManifestManagedEnvironment,
 *   accountId: string,
 *   sourceAccountId: string,
 *   sourceReaderRoleVariable: string,
 *   sourceReaderRoleArn: string,
 *   imageMetadataReaderRoleArn: string,
 *   imageMetadataAccountId: string,
 *   rawSourceMode: 'origin'|'downstream',
 *   upstreamEnvironment: ManifestManagedEnvironment|null,
 *   upstreamSourceBucketParameter: string|null,
 *   promotionRoleVariable: string,
 *   promotionRoleArn: string,
 *   etlStackName: string,
 *   chatbotStackName: string,
 *   retrievalBasePath: string,
 *   activeSelector: string,
 *   previousSelector: string,
 *   healthStateParameter: string,
 *   rollbackDegradedParameter: string,
 *   artifactPrefix: string,
 *   metricNamespace: string,
 *   resourceGroup: string,
 *   diagnosticSources: readonly string[],
 * }} RetrievalEnvironmentConfig
 */

/** @type {Readonly<Record<ManifestManagedEnvironment, RetrievalEnvironmentConfig>>} */
const CONFIGS = Object.freeze({
  qa: Object.freeze({
    environment: 'qa',
    accountId: '571600837515',
    sourceAccountId: '831926590742',
    sourceReaderRoleVariable: 'DEV_RETRIEVAL_READER_ROLE_ARN',
    sourceReaderRoleArn:
      'arn:aws:iam::831926590742:role/ki-lab-digibro-dev-retrieval-reader',
    // Immutable chatbot/ETL image metadata always originates in dev; qa reads
    // it with the same dev reader role that also serves as its raw-corpus
    // source. rawSourceMode 'origin' means qa prefers its own durable source
    // copy (via the promotion role) and falls back to dev (via the reader
    // role) only on a coordinate's first promotion (#631).
    imageMetadataReaderRoleArn:
      'arn:aws:iam::831926590742:role/ki-lab-digibro-dev-retrieval-reader',
    imageMetadataAccountId: '831926590742',
    rawSourceMode: 'origin',
    // Origin mode has no upstream durable copy to discover: qa resolves its own
    // source bucket from its own account and consults dev only as a
    // non-authoritative first-promotion fallback (a dev-specific parameter read
    // under the dev reader role, not an upstream-of-record).
    upstreamEnvironment: null,
    upstreamSourceBucketParameter: null,
    promotionRoleVariable: 'QA_RETRIEVAL_PROMOTION_ROLE_ARN',
    promotionRoleArn:
      'arn:aws:iam::571600837515:role/ki-lab-digibro-qa-retrieval-promotion',
    etlStackName: 'renate-etl-kb-qa',
    chatbotStackName: 'renate-chatbot-qa',
    retrievalBasePath: '/qa/renate/retrieval',
    activeSelector: '/qa/renate/retrieval/active-manifest',
    previousSelector: '/qa/renate/retrieval/previous-manifest',
    healthStateParameter: '/qa/renate/retrieval/health-check-state',
    rollbackDegradedParameter: '/qa/renate/retrieval/rollback-degraded',
    artifactPrefix: 'qa-retrieval',
    metricNamespace: 'Renate/QA/Retrieval',
    resourceGroup: 'deploy-qa',
    diagnosticSources: Object.freeze([
      'qa-retrieval-promotion',
      'qa-retrieval-rollback',
      'qa-retrieval-monitoring',
    ]),
  }),
  preprod: Object.freeze({
    environment: 'preprod',
    accountId: '271033482134',
    sourceAccountId: '571600837515',
    sourceReaderRoleVariable: 'QA_RETRIEVAL_SOURCE_READER_ROLE_ARN',
    sourceReaderRoleArn:
      'arn:aws:iam::571600837515:role/ki-lab-digibro-qa-retrieval-source-reader',
    // Immutable chatbot/ETL image metadata still originates in dev, so preprod
    // reads it with the dev reader role (its trust policy admits any master
    // pipeline — no bootstrap change needed). rawSourceMode 'downstream' means
    // preprod sources the composite raw corpus ONLY from QA's durable copy via
    // sourceReaderRoleArn — never from dev, never self (#631/#619).
    imageMetadataReaderRoleArn:
      'arn:aws:iam::831926590742:role/ki-lab-digibro-dev-retrieval-reader',
    imageMetadataAccountId: '831926590742',
    rawSourceMode: 'downstream',
    // The upstream of record is QA. Its source bucket name is resolved at
    // runtime from QA's own coordinate parameter, read with sourceReaderRoleArn
    // in the QA account — the same role that then reads the corpus. Keeping
    // discovery inside the entitlement means preprod cannot be pointed at a
    // bucket QA never sanctioned, and no bucket name is hand-maintained in CI.
    upstreamEnvironment: 'qa',
    upstreamSourceBucketParameter: '/qa/renate/etl-source-bucket-name',
    promotionRoleVariable: 'PREPROD_RETRIEVAL_PROMOTION_ROLE_ARN',
    promotionRoleArn:
      'arn:aws:iam::271033482134:role/ki-lab-digibro-preprod-retrieval-promotion',
    etlStackName: 'renate-etl-kb-preprod',
    chatbotStackName: 'renate-chatbot-preprod',
    retrievalBasePath: '/preprod/renate/retrieval',
    activeSelector: '/preprod/renate/retrieval/active-manifest',
    previousSelector: '/preprod/renate/retrieval/previous-manifest',
    healthStateParameter: '/preprod/renate/retrieval/health-check-state',
    rollbackDegradedParameter: '/preprod/renate/retrieval/rollback-degraded',
    artifactPrefix: 'preprod-retrieval',
    metricNamespace: 'Renate/Preprod/Retrieval',
    resourceGroup: 'deploy-preprod',
    diagnosticSources: Object.freeze([
      'preprod-retrieval-promotion',
      'preprod-retrieval-rollback',
      'preprod-retrieval-monitoring',
    ]),
  }),
  prod: Object.freeze({
    environment: 'prod',
    accountId: '718036735727',
    sourceAccountId: '571600837515',
    sourceReaderRoleVariable: 'QA_RETRIEVAL_SOURCE_READER_ROLE_ARN',
    sourceReaderRoleArn:
      'arn:aws:iam::571600837515:role/ki-lab-digibro-qa-retrieval-source-reader',
    // Image metadata comes from dev (same as qa/preprod). rawSourceMode
    // 'downstream' sources the composite raw corpus ONLY from QA's durable
    // copy via sourceReaderRoleArn — the promotion chain is dev → qa → prod,
    // NOT dev → qa → preprod → prod. Preprod is a parallel downstream.
    imageMetadataReaderRoleArn:
      'arn:aws:iam::831926590742:role/ki-lab-digibro-dev-retrieval-reader',
    imageMetadataAccountId: '831926590742',
    rawSourceMode: 'downstream',
    // Upstream of record is QA (see chain above). Source bucket name is
    // resolved at runtime from QA's own coordinate parameter, read with
    // sourceReaderRoleArn — same discovery pattern as preprod.
    upstreamEnvironment: 'qa',
    upstreamSourceBucketParameter: '/qa/renate/etl-source-bucket-name',
    promotionRoleVariable: 'PROD_RETRIEVAL_PROMOTION_ROLE_ARN',
    promotionRoleArn:
      'arn:aws:iam::718036735727:role/ki-lab-digibro-prod-retrieval-promotion',
    etlStackName: 'renate-etl-kb-prod',
    chatbotStackName: 'renate-chatbot-prod',
    retrievalBasePath: '/prod/renate/retrieval',
    activeSelector: '/prod/renate/retrieval/active-manifest',
    previousSelector: '/prod/renate/retrieval/previous-manifest',
    healthStateParameter: '/prod/renate/retrieval/health-check-state',
    rollbackDegradedParameter: '/prod/renate/retrieval/rollback-degraded',
    artifactPrefix: 'prod-retrieval',
    metricNamespace: 'Renate/Prod/Retrieval',
    resourceGroup: 'deploy-prod',
    diagnosticSources: Object.freeze([
      'prod-retrieval-promotion',
      'prod-retrieval-rollback',
      'prod-retrieval-monitoring',
    ]),
  }),
});

/**
 * @param {string} environment
 * @returns {environment is ManifestManagedEnvironment}
 */
export function isManifestManagedEnvironment(environment) {
  return Object.hasOwn(CONFIGS, environment);
}

/**
 * @param {string} environment
 * @returns {RetrievalEnvironmentConfig}
 */
export function getRetrievalEnvironmentConfig(environment) {
  if (!isManifestManagedEnvironment(environment)) {
    throw new Error(
      `unsupported retrieval environment "${environment}"; expected qa, preprod, or prod`,
    );
  }
  return CONFIGS[environment];
}

function main(argv) {
  const [command, environment, field] = argv;
  const config = getRetrievalEnvironmentConfig(environment ?? '');
  if (command === 'json') {
    process.stdout.write(`${JSON.stringify(config)}\n`);
    return;
  }
  if (command === 'field' && field && Object.hasOwn(config, field)) {
    const value = config[field];
    process.stdout.write(
      `${typeof value === 'string' ? value : JSON.stringify(value)}\n`,
    );
    return;
  }
  throw new Error(
    'usage: retrieval-environment.mjs json <qa|preprod|prod> | field <qa|preprod|prod> <field>',
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
