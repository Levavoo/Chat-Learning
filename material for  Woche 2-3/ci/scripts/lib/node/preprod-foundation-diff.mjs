#!/usr/bin/env node
// @ts-check

import fs from 'node:fs';
import util from 'node:util';

function fail(message) {
  throw new Error(`preprod foundation diff rejected: ${message}`);
}

function readTemplate(file) {
  const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  return parsed.TemplateBody ?? parsed;
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stable(item)]),
    );
  }
  return value;
}

function equal(left, right) {
  return util.isDeepStrictEqual(stable(left), stable(right));
}

function normalizedImageUri(imageUri) {
  if (typeof imageUri === 'string') return imageUri;
  if (typeof imageUri?.['Fn::Sub'] === 'string') {
    return imageUri['Fn::Sub'];
  }
  const join = imageUri?.['Fn::Join'];
  if (!Array.isArray(join) || join[0] !== '' || !Array.isArray(join[1])) {
    return imageUri;
  }
  return join[1]
    .map((part) =>
      part?.Ref === 'AWS::URLSuffix' ? '${AWS::URLSuffix}' : part,
    )
    .join('');
}

function withNormalizedImageUri(resource) {
  const clone = structuredClone(resource);
  const imageUri = clone.Properties?.Code?.ImageUri;
  if (imageUri !== undefined) {
    clone.Properties.Code.ImageUri = normalizedImageUri(imageUri);
  }
  return clone;
}

function withoutLifecycle(resource) {
  const clone = structuredClone(resource);
  if (clone.Properties) delete clone.Properties.LifecycleConfiguration;
  return clone;
}

function withoutImmutableFlag(resource) {
  const clone = structuredClone(resource);
  const variables = clone.Properties?.Environment?.Variables;
  if (variables) delete variables.BM25_IMMUTABLE_ONLY;
  return clone;
}

function withReviewedLifecycle(currentResource, proposedResource) {
  const reviewed = structuredClone(currentResource);
  const lifecycle = proposedResource.Properties?.LifecycleConfiguration;
  if (lifecycle !== undefined) {
    reviewed.Properties ??= {};
    reviewed.Properties.LifecycleConfiguration = structuredClone(lifecycle);
  }
  return reviewed;
}

function disabledSourceReprocessFunction(currentResource) {
  const reviewed = structuredClone(currentResource);
  reviewed.Properties ??= {};
  reviewed.Properties.Environment ??= {};
  reviewed.Properties.Environment.Variables ??= {};
  reviewed.Properties.Environment.Variables.SOURCE_REPROCESS_ENABLED = 'false';
  return reviewed;
}

function isRetainedSourceReprocess(logicalId) {
  return logicalId.includes('SourceReprocessTrigger');
}

function isAllowedGreenAddition(logicalId) {
  return logicalId.includes('Green') || logicalId.includes('Slot');
}

function stringParameterName(resource) {
  return resource.Type === 'AWS::SSM::Parameter'
    ? resource.Properties?.Name
    : undefined;
}

function policyActions(resource) {
  const documents = [];
  if (resource.Properties?.Policies) {
    documents.push(
      ...resource.Properties.Policies.map((policy) => policy.PolicyDocument),
    );
  }
  if (resource.Properties?.PolicyDocument) {
    documents.push(resource.Properties.PolicyDocument);
  }
  return documents.flatMap((document) =>
    (document?.Statement ?? []).flatMap((statement) => {
      const actions = statement.Action ?? [];
      return Array.isArray(actions) ? actions : [actions];
    }),
  );
}

export function prepareFoundationTemplate(currentTemplate, proposedTemplate) {
  const current = currentTemplate.Resources ?? {};
  const proposed = proposedTemplate.Resources ?? {};
  const reviewed = structuredClone(proposedTemplate);
  reviewed.Resources = {};

  for (const [logicalId, currentResource] of Object.entries(current)) {
    const proposedResource = proposed[logicalId];
    if (proposedResource && currentResource.Type !== proposedResource.Type) {
      fail(`existing resource ${logicalId} changes type`);
    }

    if (proposedResource && currentResource.Type === 'AWS::S3::Bucket') {
      reviewed.Resources[logicalId] = withReviewedLifecycle(
        currentResource,
        proposedResource,
      );
      continue;
    }

    if (
      proposedResource &&
      logicalId.includes('SourceReprocessTriggerReprocessRole') &&
      proposedResource.Type === 'AWS::IAM::Role'
    ) {
      if (
        policyActions(proposedResource).some((action) =>
          ['s3:PutObject', 's3:PutObjectTagging'].includes(action),
        )
      ) {
        fail('disabled SourceReprocess role retains S3 write access');
      }
      reviewed.Resources[logicalId] = structuredClone(proposedResource);
      continue;
    }

    if (
      proposedResource &&
      logicalId.includes('SourceReprocessTriggerReprocessFunction') &&
      proposedResource.Type === 'AWS::Lambda::Function'
    ) {
      reviewed.Resources[logicalId] =
        disabledSourceReprocessFunction(currentResource);
      continue;
    }

    // The foundation operation preserves every other legacy resource byte for
    // byte. This retains old custom resources and asset coordinates that are
    // no longer synthesized by current CDK code without deleting or invoking
    // them during the additive migration.
    reviewed.Resources[logicalId] = structuredClone(currentResource);
  }

  for (const [logicalId, resource] of Object.entries(proposed)) {
    if (current[logicalId] || !isAllowedGreenAddition(logicalId)) continue;
    reviewed.Resources[logicalId] = structuredClone(resource);
  }

  reviewed.Outputs = structuredClone(currentTemplate.Outputs ?? {});
  for (const [logicalId, output] of Object.entries(
    proposedTemplate.Outputs ?? {},
  )) {
    if (logicalId.includes('Green')) {
      reviewed.Outputs[logicalId] = structuredClone(output);
    }
  }

  return reviewed;
}

export function validateFoundationDiff(currentTemplate, proposedTemplate) {
  const current = currentTemplate.Resources ?? {};
  const proposed = proposedTemplate.Resources ?? {};
  const reviewedChanges = [];

  const serialized = JSON.stringify(proposedTemplate);
  if (
    serialized.includes('/preprod/renate/retrieval/active-manifest') ||
    serialized.includes('/preprod/renate/retrieval/previous-manifest')
  ) {
    fail('synthesized template owns a promotion selector');
  }

  for (const [logicalId, currentResource] of Object.entries(current)) {
    const proposedResource = proposed[logicalId];
    if (!proposedResource) fail(`existing resource ${logicalId} is deleted`);
    if (currentResource.Type !== proposedResource.Type) {
      fail(`existing resource ${logicalId} changes type`);
    }
    if (equal(currentResource, proposedResource)) continue;
    if (
      currentResource.Type === 'AWS::Lambda::Function' &&
      equal(
        withNormalizedImageUri(currentResource),
        withNormalizedImageUri(proposedResource),
      )
    ) {
      reviewedChanges.push(logicalId);
      continue;
    }

    if (
      currentResource.Type === 'AWS::S3::Bucket' &&
      equal(
        withoutLifecycle(currentResource),
        withoutLifecycle(proposedResource),
      )
    ) {
      reviewedChanges.push(logicalId);
      continue;
    }

    if (
      logicalId.includes('Bm25IndexBuilderBuilderLambda') &&
      equal(
        withoutImmutableFlag(currentResource),
        withoutImmutableFlag(proposedResource),
      ) &&
      proposedResource.Properties?.Environment?.Variables
        ?.BM25_IMMUTABLE_ONLY === 'true'
    ) {
      reviewedChanges.push(logicalId);
      continue;
    }

    if (isRetainedSourceReprocess(logicalId)) {
      if (
        proposedResource.Type === 'AWS::IAM::Role' &&
        policyActions(proposedResource).some((action) =>
          ['s3:PutObject', 's3:PutObjectTagging'].includes(action),
        )
      ) {
        fail('disabled SourceReprocess role retains S3 write access');
      }
      if (
        proposedResource.Type === 'AWS::Lambda::Function' &&
        proposedResource.Properties?.Environment?.Variables
          ?.SOURCE_REPROCESS_ENABLED !== 'false'
      ) {
        fail('retained SourceReprocess Lambda is not disabled');
      }
      reviewedChanges.push(logicalId);
      continue;
    }

    fail(`unexpected change to existing resource ${logicalId}`);
  }

  const additions = [];
  for (const [logicalId, resource] of Object.entries(proposed)) {
    if (current[logicalId]) continue;
    if (!isAllowedGreenAddition(logicalId)) {
      fail(`unexpected new resource ${logicalId}`);
    }
    const parameterName = stringParameterName(resource);
    if (
      parameterName &&
      !String(parameterName).startsWith('/preprod/renate/retrieval/slots/')
    ) {
      fail(`new SSM parameter ${logicalId} is not a slot coordinate`);
    }
    additions.push(logicalId);
  }

  const greenProcessed = Object.entries(proposed).find(
    ([logicalId, resource]) =>
      logicalId.includes('GreenProcessedBucket') &&
      resource.Type === 'AWS::S3::Bucket',
  )?.[1];
  if (!greenProcessed) fail('green processed bucket is missing');
  if (
    greenProcessed.Properties?.VersioningConfiguration?.Status !== 'Enabled'
  ) {
    fail('green processed bucket is not versioned');
  }
  if (
    greenProcessed.DeletionPolicy !== 'Retain' ||
    greenProcessed.UpdateReplacePolicy !== 'Retain'
  ) {
    fail('green processed bucket is not retained');
  }

  for (const [logicalId, resource] of Object.entries(proposed)) {
    if (
      logicalId.includes('GreenBedrockKBVector') &&
      resource.Type.startsWith('AWS::S3Vectors::') &&
      (resource.DeletionPolicy !== 'Retain' ||
        resource.UpdateReplacePolicy !== 'Retain')
    ) {
      fail(`green vector resource ${logicalId} is not retained`);
    }
  }

  return {
    existingResources: Object.keys(current).length,
    reviewedChanges: reviewedChanges.sort(),
    additions: additions.sort(),
  };
}

function main(argv) {
  if (argv[0] === 'prepare') {
    if (argv.length !== 4) {
      fail('usage: preprod-foundation-diff.mjs prepare CURRENT SYNTH REVIEWED');
    }
    const reviewed = prepareFoundationTemplate(
      readTemplate(argv[1]),
      readTemplate(argv[2]),
    );
    validateFoundationDiff(readTemplate(argv[1]), reviewed);
    fs.writeFileSync(argv[3], `${JSON.stringify(reviewed, null, 2)}\n`);
    return;
  }
  if (argv.length !== 2) {
    fail('usage: preprod-foundation-diff.mjs CURRENT_TEMPLATE SYNTH_TEMPLATE');
  }
  const result = validateFoundationDiff(
    readTemplate(argv[0]),
    readTemplate(argv[1]),
  );
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
