import test from 'node:test';
import assert from 'node:assert/strict';

import {
  prepareFoundationTemplate,
  validateFoundationDiff,
} from '../../../lib/node/preprod-foundation-diff.mjs';

function legacyTemplate() {
  return {
    Resources: {
      BlueBucket: {
        Type: 'AWS::S3::Bucket',
        Properties: { BucketName: 'legacy-blue' },
      },
      TransformLambda: {
        Type: 'AWS::Lambda::Function',
        Properties: {
          Code: { ImageUri: 'repo@sha256:legacy' },
          Environment: { Variables: { DESTINATION_BUCKET: 'legacy-blue' } },
        },
      },
      Bm25IndexBuilderBuilderLambda: {
        Type: 'AWS::Lambda::Function',
        Properties: {
          Code: { ImageUri: 'repo@sha256:legacy' },
          Environment: { Variables: { BM25_BUCKET: 'legacy-blue' } },
        },
      },
      SourceReprocessTriggerReprocessFunction: {
        Type: 'AWS::Lambda::Function',
        Properties: {
          Code: { S3Key: 'legacy-reprocess.zip' },
          Environment: { Variables: {} },
        },
      },
      SourceReprocessTriggerReprocessRole: {
        Type: 'AWS::IAM::Role',
        Properties: {
          Policies: [
            {
              PolicyDocument: {
                Statement: [{ Action: ['s3:GetObject', 's3:PutObject'] }],
              },
            },
          ],
        },
      },
      LegacySeeder: {
        Type: 'AWS::CloudFormation::CustomResource',
        Properties: { ServiceToken: 'legacy-provider' },
      },
    },
  };
}

function acceptedTemplate() {
  const template = structuredClone(legacyTemplate());
  template.Resources.BlueBucket.Properties.LifecycleConfiguration = {
    Rules: [{ Id: 'Retain', Status: 'Enabled' }],
  };
  template.Resources.Bm25IndexBuilderBuilderLambda.Properties.Environment.Variables.BM25_IMMUTABLE_ONLY =
    'true';
  template.Resources.SourceReprocessTriggerReprocessFunction.Properties.Environment.Variables.SOURCE_REPROCESS_ENABLED =
    'false';
  template.Resources.SourceReprocessTriggerReprocessRole.Properties.Policies =
    [];
  template.Resources.GreenProcessedBucket = {
    Type: 'AWS::S3::Bucket',
    DeletionPolicy: 'Retain',
    UpdateReplacePolicy: 'Retain',
    Properties: {
      BucketName: 'green-preprod',
      VersioningConfiguration: { Status: 'Enabled' },
    },
  };
  template.Resources.GreenBedrockKBVectorBucket = {
    Type: 'AWS::S3Vectors::VectorBucket',
    DeletionPolicy: 'Retain',
    UpdateReplacePolicy: 'Retain',
    Properties: { VectorBucketName: 'green-vector' },
  };
  template.Resources.GreenSlotKnowledgeBaseIdParameter = {
    Type: 'AWS::SSM::Parameter',
    Properties: {
      Name: '/preprod/renate/retrieval/slots/green/knowledge-base-id',
      Value: 'green-kb',
    },
  };
  return template;
}

test('accepts only additive green and reviewed in-place changes', () => {
  const result = validateFoundationDiff(legacyTemplate(), acceptedTemplate());
  assert.equal(result.existingResources, 6);
  assert.ok(result.additions.includes('GreenProcessedBucket'));
});

test('prepares an additive migration template that preserves legacy resources', () => {
  const current = legacyTemplate();
  current.Outputs = { LegacyOutput: { Value: 'legacy' } };
  const synth = acceptedTemplate();
  delete synth.Resources.LegacySeeder;
  synth.Resources.SourceReprocessTriggerReprocessFunction.Properties.Code.S3Key =
    'new-reprocess.zip';
  synth.Resources.UnrelatedParameter = {
    Type: 'AWS::SSM::Parameter',
    Properties: { Name: '/preprod/unrelated', Value: 'no' },
  };
  synth.Outputs = {
    GreenKnowledgeBaseId: { Value: 'green-kb' },
    UnrelatedOutput: { Value: 'no' },
  };

  const reviewed = prepareFoundationTemplate(current, synth);

  assert.deepEqual(
    reviewed.Resources.LegacySeeder,
    current.Resources.LegacySeeder,
  );
  assert.equal(
    reviewed.Resources.SourceReprocessTriggerReprocessFunction.Properties.Code
      .S3Key,
    'legacy-reprocess.zip',
  );
  assert.equal(
    reviewed.Resources.SourceReprocessTriggerReprocessFunction.Properties
      .Environment.Variables.SOURCE_REPROCESS_ENABLED,
    'false',
  );
  assert.ok(reviewed.Resources.BlueBucket.Properties.LifecycleConfiguration);
  assert.equal(reviewed.Resources.UnrelatedParameter, undefined);
  assert.deepEqual(reviewed.Outputs, {
    LegacyOutput: { Value: 'legacy' },
    GreenKnowledgeBaseId: { Value: 'green-kb' },
  });
  assert.doesNotThrow(() => validateFoundationDiff(current, reviewed));
});

test('accepts equivalent Lambda image URI intrinsic encodings', () => {
  const current = legacyTemplate();
  current.Resources.TransformLambda.Properties.Code.ImageUri = {
    'Fn::Sub':
      '123456789012.dkr.ecr.eu-central-1.${AWS::URLSuffix}/repo:immutable',
  };
  const proposed = acceptedTemplate();
  proposed.Resources.TransformLambda.Properties.Code.ImageUri = {
    'Fn::Join': [
      '',
      [
        '123456789012.dkr.ecr.eu-central-1.',
        { Ref: 'AWS::URLSuffix' },
        '/repo:immutable',
      ],
    ],
  };
  assert.doesNotThrow(() => validateFoundationDiff(current, proposed));
});

test('rejects deletion of a legacy resource', () => {
  const proposed = acceptedTemplate();
  delete proposed.Resources.TransformLambda;
  assert.throws(
    () => validateFoundationDiff(legacyTemplate(), proposed),
    /existing resource TransformLambda is deleted/,
  );
});

test('rejects a selector resource', () => {
  const proposed = acceptedTemplate();
  proposed.Resources.ActiveSelector = {
    Type: 'AWS::SSM::Parameter',
    Properties: {
      Name: '/preprod/renate/retrieval/active-manifest',
      Value: '{}',
    },
  };
  assert.throws(
    () => validateFoundationDiff(legacyTemplate(), proposed),
    /owns a promotion selector/,
  );
});

test('rejects transform destination or image drift', () => {
  const proposed = acceptedTemplate();
  proposed.Resources.TransformLambda.Properties.Environment.Variables.DESTINATION_BUCKET =
    'green-preprod';
  assert.throws(
    () => validateFoundationDiff(legacyTemplate(), proposed),
    /unexpected change to existing resource TransformLambda/,
  );
});
