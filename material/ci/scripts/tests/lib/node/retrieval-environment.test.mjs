import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getRetrievalEnvironmentConfig,
  isManifestManagedEnvironment,
} from '../../../lib/node/retrieval-environment.mjs';

test('manifest-managed environment config preserves QA and defines preprod and prod', () => {
  const qa = getRetrievalEnvironmentConfig('qa');
  const preprod = getRetrievalEnvironmentConfig('preprod');
  const prod = getRetrievalEnvironmentConfig('prod');

  assert.equal(qa.activeSelector, '/qa/renate/retrieval/active-manifest');
  assert.equal(qa.resourceGroup, 'deploy-qa');
  assert.equal(preprod.accountId, '271033482134');
  assert.equal(
    preprod.sourceReaderRoleArn,
    'arn:aws:iam::571600837515:role/ki-lab-digibro-qa-retrieval-source-reader',
  );
  assert.equal(
    preprod.promotionRoleArn,
    'arn:aws:iam::271033482134:role/ki-lab-digibro-preprod-retrieval-promotion',
  );
  assert.equal(
    preprod.activeSelector,
    '/preprod/renate/retrieval/active-manifest',
  );
  assert.equal(preprod.metricNamespace, 'Renate/Preprod/Retrieval');
  assert.equal(preprod.resourceGroup, 'deploy-preprod');
  // #726: prod is a parallel downstream of qa — same qa source-reader role as
  // preprod (dev → qa → {preprod, prod}, not a preprod → prod chain).
  assert.equal(prod.accountId, '718036735727');
  assert.equal(
    prod.sourceReaderRoleArn,
    'arn:aws:iam::571600837515:role/ki-lab-digibro-qa-retrieval-source-reader',
  );
  assert.equal(
    prod.promotionRoleArn,
    'arn:aws:iam::718036735727:role/ki-lab-digibro-prod-retrieval-promotion',
  );
  assert.equal(prod.activeSelector, '/prod/renate/retrieval/active-manifest');
  assert.equal(prod.metricNamespace, 'Renate/Prod/Retrieval');
  assert.equal(prod.resourceGroup, 'deploy-prod');
});

test('image metadata always sources from dev; raw-source mode is per-env (#643/#631/#726)', () => {
  const qa = getRetrievalEnvironmentConfig('qa');
  const preprod = getRetrievalEnvironmentConfig('preprod');
  const prod = getRetrievalEnvironmentConfig('prod');
  const devReader =
    'arn:aws:iam::831926590742:role/ki-lab-digibro-dev-retrieval-reader';

  // Chatbot/ETL image metadata originates in dev for ALL environments — the
  // dev reader's trust policy admits any master pipeline, so no bootstrap
  // change is needed for downstream envs to read it.
  assert.equal(qa.imageMetadataReaderRoleArn, devReader);
  assert.equal(preprod.imageMetadataReaderRoleArn, devReader);
  assert.equal(prod.imageMetadataReaderRoleArn, devReader);
  assert.equal(qa.imageMetadataAccountId, '831926590742');
  assert.equal(preprod.imageMetadataAccountId, '831926590742');
  assert.equal(prod.imageMetadataAccountId, '831926590742');

  // qa is the origin (self-preferred, dev fallback on first promotion);
  // preprod and prod are parallel downstreams (QA durable copy only, never
  // dev, never self, never each other).
  assert.equal(qa.rawSourceMode, 'origin');
  assert.equal(preprod.rawSourceMode, 'downstream');
  assert.equal(prod.rawSourceMode, 'downstream');
});

test('#643/#726: every downstream environment names an upstream of record', () => {
  const qa = getRetrievalEnvironmentConfig('qa');
  const preprod = getRetrievalEnvironmentConfig('preprod');
  const prod = getRetrievalEnvironmentConfig('prod');
  // Origin mode has no durable upstream to discover.
  assert.equal(qa.upstreamEnvironment, null);
  assert.equal(qa.upstreamSourceBucketParameter, null);
  // Preprod and prod both resolve QA's bucket name from QA's own coordinate
  // parameter, so no bucket name has to be configured in CI (#643/#726).
  for (const downstream of [preprod, prod]) {
    assert.equal(downstream.upstreamEnvironment, 'qa');
    assert.equal(
      downstream.upstreamSourceBucketParameter,
      '/qa/renate/etl-source-bucket-name',
    );
    // The parameter must live in the account the source-reader role targets,
    // otherwise the read cannot succeed under that single entitlement.
    assert.ok(
      downstream.sourceReaderRoleArn.includes(downstream.sourceAccountId),
      'source reader role must be in the upstream account',
    );
    assert.ok(
      downstream.upstreamSourceBucketParameter.startsWith(
        `/${downstream.upstreamEnvironment}/`,
      ),
      'upstream parameter must be namespaced to the upstream environment',
    );
  }
});

test('environment config fails closed outside qa/preprod/prod', () => {
  assert.equal(isManifestManagedEnvironment('qa'), true);
  assert.equal(isManifestManagedEnvironment('preprod'), true);
  assert.equal(isManifestManagedEnvironment('prod'), true);
  assert.equal(isManifestManagedEnvironment('dev'), false);
  assert.throws(
    () => getRetrievalEnvironmentConfig('dev'),
    /expected qa, preprod, or prod/,
  );
  assert.throws(
    () => getRetrievalEnvironmentConfig('bogus'),
    /expected qa, preprod, or prod/,
  );
});
