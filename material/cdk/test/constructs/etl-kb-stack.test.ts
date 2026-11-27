import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';

import { EtlKnowledgeBaseStack } from '../../lib/etl-kb-stack';
import { etlParametersMap } from '../../parameter';

const minimalEtlConfig = {
  lambdaTimeoutSeconds: 300,
  lambdaMemorySizeMb: 1024,
  batchSize: 10,
  batchWindowSeconds: 30,
  visibilityTimeoutSeconds: 360,
  messageRetentionDays: 4,
  maxReceiveCount: 3,
};

function buildTemplate(): Template {
  const app = new App();
  const stack = new EtlKnowledgeBaseStack(app, 'TestEtlKbStack', {
    envName: 'dev',
    kbStackName: 'renate-etl-kb-dev',
    kbDescription: 'Test KB stack',
    vectorDimension: 1024,
    etlConfig: minimalEtlConfig,
    etlEcrAccount: '831926590742',
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  return Template.fromStack(stack);
}

function buildTemplateWithChunking(): Template {
  const app = new App();
  const stack = new EtlKnowledgeBaseStack(app, 'TestEtlKbStackChunking', {
    envName: 'dev',
    kbStackName: 'renate-etl-kb-dev',
    kbDescription: 'Test KB stack',
    vectorDimension: 1024,
    etlConfig: { ...minimalEtlConfig, chunking: { enabled: true } },
    etlEcrAccount: '831926590742',
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  return Template.fromStack(stack);
}

function buildQaFoundationTemplate(): Template {
  const app = new App({
    context: {
      etlImageTag: 'v1.105.0',
      retrievalCandidateSlot: 'green',
      blueEtlImageTag: 'v1.83.3-qa-blue-baseline',
      greenEtlImageTag: 'v1.105.0',
    },
  });
  const stack = new EtlKnowledgeBaseStack(app, 'TestQaEtlKbStack', {
    envName: 'qa',
    kbStackName: 'renate-etl-kb-qa',
    kbDescription: 'Test QA KB stack',
    vectorDimension: 1024,
    etlConfig: minimalEtlConfig,
    etlEcrAccount: '831926590742',
    env: { account: '123456789012', region: 'eu-central-1' },
  });
  return Template.fromStack(stack);
}

function buildPreprodFoundationTemplate(): Template {
  const digest = `sha256:${'a'.repeat(64)}`;
  const app = new App({
    context: {
      etlImageTag: digest,
      retrievalCandidateSlot: 'blue',
      blueEtlImageTag: digest,
      greenEtlImageTag: digest,
    },
  });
  const stack = new EtlKnowledgeBaseStack(app, 'TestPreprodEtlKbStack', {
    envName: 'preprod',
    kbStackName: 'renate-etl-kb-preprod',
    kbDescription: 'Test preprod KB stack',
    vectorDimension: 1024,
    etlConfig: minimalEtlConfig,
    etlEcrAccount: '831926590742',
    env: { account: '271033482134', region: 'eu-central-1' },
  });
  return Template.fromStack(stack);
}

// #668: prod is manifest-managed. Mirrors the preprod foundation build (candidate
// slot blue, one immutable digest for all three image coordinates) on the real
// prod account, and passes official alertEmails so the AlertingTopic exists — that
// lets the tests prove EtlAlarms/GreenEtlAlarms keep their SNS actions while the
// prod RetrievalHealthAlarms are deliberately actionless.
function buildProdFoundationTemplate(
  retrievalHealthAlarmActionsEnabled = false,
): Template {
  const digest = `sha256:${'c'.repeat(64)}`;
  const app = new App({
    context: {
      env: 'prod',
      environment: 'prod',
      etlImageTag: digest,
      retrievalCandidateSlot: 'blue',
      blueEtlImageTag: digest,
      greenEtlImageTag: digest,
    },
  });
  const stack = new EtlKnowledgeBaseStack(app, 'TestProdEtlKbStack', {
    envName: 'prod',
    kbStackName: 'renate-etl-kb-prod',
    kbDescription: 'Test prod KB stack',
    vectorDimension: 1024,
    etlConfig: minimalEtlConfig,
    etlEcrAccount: '831926590742',
    alertEmails: ['renate-ops@example.com'],
    retrievalHealthAlarmActionsEnabled,
    env: { account: '718036735727', region: 'eu-central-1' },
  });
  return Template.fromStack(stack);
}

describe('#591 — environment seeding configuration removed', () => {
  test.each(['dev', 'qa', 'demo', 'preprod', 'prod'])(
    '%s has no legacy seeding configuration',
    (envName) => {
      const parameters = etlParametersMap.get(envName);

      expect(parameters).toBeDefined();
      expect(parameters).not.toHaveProperty('seeding');
    },
  );
});

describe('#491 — QA green retrieval foundation', () => {
  let qaTemplate: Template;

  beforeAll(() => {
    qaTemplate = buildQaFoundationTemplate();
  });

  test('preserves blue logical resources and adds one isolated green KB/data source/vector store', () => {
    const knowledgeBases = qaTemplate.findResources(
      'AWS::Bedrock::KnowledgeBase',
    );
    const dataSources = qaTemplate.findResources('AWS::Bedrock::DataSource');
    const vectorBuckets = qaTemplate.findResources(
      'AWS::S3Vectors::VectorBucket',
    );
    const vectorIndexes = qaTemplate.findResources('AWS::S3Vectors::Index');

    expect(Object.keys(knowledgeBases)).toHaveLength(2);
    expect(Object.keys(dataSources)).toHaveLength(2);
    expect(Object.keys(vectorBuckets)).toHaveLength(2);
    expect(Object.keys(vectorIndexes)).toHaveLength(2);
    expect(Object.keys(knowledgeBases)).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^BedrockKB/),
        expect.stringMatching(/^GreenBedrockKB/),
      ]),
    );
  });

  test('green processed bucket is versioned and has its own immutable-only BM25 builder', () => {
    const greenBuckets = qaTemplate.findResources('AWS::S3::Bucket', {
      Properties: { VersioningConfiguration: { Status: 'Enabled' } },
    });
    expect(Object.keys(greenBuckets)).toEqual(
      expect.arrayContaining([expect.stringMatching(/^GreenProcessedBucket/)]),
    );

    qaTemplate.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          BM25_IMMUTABLE_ONLY: 'true',
          BM25_INDEX_KEY: 'bm25_index/index.json',
        }),
      },
    });
  });

  test('green cleanup resources use distinct physical names', () => {
    const cleanupFunctions = qaTemplate.findResources('AWS::Lambda::Function', {
      Properties: {
        FunctionName: Match.stringLikeRegexp('bedrock-cleanup'),
      },
    });
    const cleanupRoles = qaTemplate.findResources('AWS::IAM::Role', {
      Properties: {
        RoleName: Match.stringLikeRegexp('bedrock-cleanup-role'),
      },
    });

    const functionNames = Object.values(cleanupFunctions).map(
      (resource) =>
        (resource as { Properties: { FunctionName: string } }).Properties
          .FunctionName,
    );
    const roleNames = Object.values(cleanupRoles).map(
      (resource) =>
        (resource as { Properties: { RoleName: string } }).Properties.RoleName,
    );

    expect(functionNames).toHaveLength(2);
    expect(new Set(functionNames).size).toBe(2);
    expect(functionNames).toEqual(
      expect.arrayContaining([
        expect.stringContaining('bedrock-cleanup-green'),
      ]),
    );
    expect(roleNames).toHaveLength(2);
    expect(new Set(roleNames).size).toBe(2);
    expect(roleNames).toEqual(
      expect.arrayContaining([
        expect.stringContaining('bedrock-cleanup-role-green'),
      ]),
    );
  });

  test('publishes blue/green slot coordinates but deliberately creates no active selector', () => {
    for (const slot of ['blue', 'green']) {
      for (const coordinate of [
        'knowledge-base-id',
        'data-source-id',
        'processed-bucket-name',
        'kb-sync-function-name',
        'bm25-builder-function-name',
        'bm25-rebuild-queue-arn',
        'bm25-rebuild-dlq-arn',
        'bm25-releases-prefix',
      ]) {
        qaTemplate.hasResourceProperties('AWS::SSM::Parameter', {
          Name: `/qa/renate/retrieval/slots/${slot}/${coordinate}`,
          Type: 'String',
        });
      }
    }

    for (const selector of ['active-manifest', 'previous-manifest']) {
      const selectors = qaTemplate.findResources('AWS::SSM::Parameter', {
        Properties: {
          Name: `/qa/renate/retrieval/${selector}`,
        },
      });
      expect(Object.keys(selectors)).toHaveLength(0);
    }
  });

  test('dev remains single-slot', () => {
    const devTemplate = buildTemplate();
    devTemplate.resourceCountIs('AWS::Bedrock::KnowledgeBase', 1);
    devTemplate.resourceCountIs('AWS::Bedrock::DataSource', 1);
    const slotParams = devTemplate.findResources('AWS::SSM::Parameter', {
      Properties: { Name: Match.stringLikeRegexp('/retrieval/slots/') },
    });
    expect(Object.keys(slotParams)).toHaveLength(0);
  });
});

describe('#641 — preprod shared green retrieval foundation', () => {
  let template: Template;

  beforeAll(() => {
    template = buildPreprodFoundationTemplate();
  });

  test('uses the same two-slot path without owning selectors', () => {
    template.resourceCountIs('AWS::Bedrock::KnowledgeBase', 2);
    template.resourceCountIs('AWS::Bedrock::DataSource', 2);
    for (const slot of ['blue', 'green']) {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: `/preprod/renate/retrieval/slots/${slot}/knowledge-base-id`,
      });
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: `/preprod/renate/retrieval/slots/${slot}/processed-bucket-name`,
      });
    }
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).not.toContain(
      '/preprod/renate/retrieval/active-manifest',
    );
    expect(serialized).not.toContain(
      '/preprod/renate/retrieval/previous-manifest',
    );
  });

  test('new green storage uses preprod physical names while legacy blue keeps its existing name contract', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    const green = Object.entries(buckets).find(([id]) =>
      id.startsWith('GreenProcessedBucket'),
    )?.[1] as any;
    const blue = Object.entries(buckets).find(([id]) =>
      id.startsWith('IngestionBucket'),
    )?.[1] as any;

    expect(green.Properties.BucketName).toContain(
      'retrieval-green-processed-preprod-',
    );
    expect(green.Properties.VersioningConfiguration.Status).toBe('Enabled');
    expect(green.DeletionPolicy).toBe('Retain');
    expect(blue.Properties.BucketName).toContain('kb-ingestion-bucket-dev-');
  });

  test('retains but disables the legacy SourceReprocess path and strips its write access', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: {
          SOURCE_REPROCESS_ENABLED: 'false',
        },
      },
    });
    const roles = template.findResources('AWS::IAM::Role');
    const reprocessRole = Object.entries(roles).find(([id]) =>
      id.includes('SourceReprocessTriggerReprocessRole'),
    )?.[1];
    expect(reprocessRole).toBeDefined();
    expect(JSON.stringify(reprocessRole)).not.toContain('s3:PutObject');
  });

  test('#643: creates the scheduled retrieval heartbeat alarms on the preprod namespace', () => {
    // #641 deliberately deferred these (no preprod health schedule existed
    // yet, and CheckExecutedAlarm treats missing data as BREACHING). #643 adds
    // .gitlab/ci/deploy/preprod/retrieval-health-check.yml, so preprod now
    // gets the same four alarms as qa — bound to Renate/Preprod/Retrieval.
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const retrievalAlarms = Object.entries(alarms).filter(([id]) =>
      id.includes('RetrievalHealthAlarms'),
    );
    expect(retrievalAlarms).toHaveLength(4);
    for (const [, alarm] of retrievalAlarms) {
      expect((alarm as any).Properties.Namespace).toBe(
        'Renate/Preprod/Retrieval',
      );
    }
    const metricNames = retrievalAlarms
      .map(([, alarm]) => (alarm as any).Properties.MetricName)
      .sort();
    expect(metricNames).toEqual([
      'CheckExecuted',
      'CoherenceFailure',
      'IngestionFailure',
      'RetentionPinMissing',
    ]);
  });
});

describe('#668 — prod manifest-managed foundation', () => {
  let template: Template;

  beforeAll(() => {
    template = buildProdFoundationTemplate();
  });

  test('prod is manifest-managed with two coherent retrieval slots', () => {
    template.resourceCountIs('AWS::Bedrock::KnowledgeBase', 2);
    template.resourceCountIs('AWS::Bedrock::DataSource', 2);
    template.resourceCountIs('AWS::S3Vectors::VectorBucket', 2);
    template.resourceCountIs('AWS::S3Vectors::Index', 2);
  });

  test('publishes exactly 16 slot coordinates (8 per slot) and no others', () => {
    for (const slot of ['blue', 'green']) {
      for (const coordinate of [
        'knowledge-base-id',
        'data-source-id',
        'processed-bucket-name',
        'kb-sync-function-name',
        'bm25-builder-function-name',
        'bm25-rebuild-queue-arn',
        'bm25-rebuild-dlq-arn',
        'bm25-releases-prefix',
      ]) {
        template.hasResourceProperties('AWS::SSM::Parameter', {
          Name: `/prod/renate/retrieval/slots/${slot}/${coordinate}`,
          Type: 'String',
        });
      }
    }
    const slotParams = template.findResources('AWS::SSM::Parameter', {
      Properties: {
        Name: Match.stringLikeRegexp('/prod/renate/retrieval/slots/'),
      },
    });
    expect(Object.keys(slotParams)).toHaveLength(16);
  });

  test('creates no active/previous retrieval selector', () => {
    for (const selector of ['active-manifest', 'previous-manifest']) {
      const selectors = template.findResources('AWS::SSM::Parameter', {
        Properties: { Name: `/prod/renate/retrieval/${selector}` },
      });
      expect(Object.keys(selectors)).toHaveLength(0);
    }
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).not.toContain('/prod/renate/retrieval/active-manifest');
    expect(serialized).not.toContain(
      '/prod/renate/retrieval/previous-manifest',
    );
  });

  test('new green resources are prod-suffixed with retained data semantics', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    const green = Object.entries(buckets).find(([id]) =>
      id.startsWith('GreenProcessedBucket'),
    )?.[1] as any;
    expect(green).toBeDefined();
    expect(green.Properties.BucketName).toContain(
      'retrieval-green-processed-prod-',
    );
    expect(green.Properties.VersioningConfiguration.Status).toBe('Enabled');
    expect(green.DeletionPolicy).toBe('Retain');

    // Green KB vector store + data source are retained on rollback/delete
    // (the #668 RETAIN spread extended from preprod to prod).
    const vectorBuckets = template.findResources(
      'AWS::S3Vectors::VectorBucket',
    );
    const greenVectorBucket = Object.entries(vectorBuckets).find(([id]) =>
      id.startsWith('GreenBedrockKB'),
    )?.[1] as any;
    expect(greenVectorBucket).toBeDefined();
    expect(greenVectorBucket.DeletionPolicy).toBe('Retain');

    const dataSources = template.findResources('AWS::Bedrock::DataSource');
    const greenDataSource = Object.entries(dataSources).find(([id]) =>
      id.startsWith('GreenBedrockKB'),
    )?.[1] as any;
    expect(greenDataSource).toBeDefined();
    expect(greenDataSource.Properties.DataDeletionPolicy).toBe('RETAIN');
  });

  test('legacy blue bucket resolves to its live prod physical-name contract', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    const blue = Object.entries(buckets).find(([id]) =>
      id.startsWith('IngestionBucket'),
    )?.[1] as any;
    expect(blue).toBeDefined();
    expect(blue.Properties.BucketName).toContain('kb-ingestion-bucket-prod-');
    expect(blue.Properties.BucketName).not.toContain(
      'kb-ingestion-bucket-dev-',
    );
  });

  test('uses explicit Prod lifecycle IDs for both retrieval slots', () => {
    const buckets = template.findResources('AWS::S3::Bucket');
    const lifecycleIds = Object.values(buckets).flatMap((bucket: any) =>
      (bucket.Properties?.LifecycleConfiguration?.Rules ?? []).map(
        (rule: any) => rule.Id,
      ),
    );

    expect(lifecycleIds).toEqual(
      expect.arrayContaining([
        'ProdBlueRetrieval-ProcessedReleases-ExpireUnpinned',
        'ProdBlueRetrieval-Bm25_indexReleases-ExpireUnpinned',
        'ProdBlueRetrieval-Retrieval-manifestsReleases-ExpireUnpinned',
        'ProdGreenRetrieval-ProcessedReleases-ExpireUnpinned',
        'ProdGreenRetrieval-Bm25_indexReleases-ExpireUnpinned',
        'ProdGreenRetrieval-Retrieval-manifestsReleases-ExpireUnpinned',
      ]),
    );
    expect(lifecycleIds.some((id: string) => id.startsWith('Preprod'))).toBe(
      false,
    );
  });

  test('uses the Renate/Prod/Retrieval namespace with no preprod/demo leakage', () => {
    const serialized = JSON.stringify(template.toJSON());
    expect(serialized).toContain('Renate/Prod/Retrieval');
    // No cross-environment leakage from the preprod/demo templates this path
    // was parameterized from.
    expect(serialized).not.toContain('preprod');
    expect(serialized).not.toContain('271033482134'); // preprod account
    expect(serialized).not.toContain('254992224283'); // demo account
  });

  test('SourceReprocess is retained but disabled with no source-write authority', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: {
          SOURCE_REPROCESS_ENABLED: 'false',
        },
      },
    });
    const roles = template.findResources('AWS::IAM::Role');
    const reprocessRole = Object.entries(roles).find(([id]) =>
      id.includes('SourceReprocessTriggerReprocessRole'),
    )?.[1];
    expect(reprocessRole).toBeDefined();
    expect(JSON.stringify(reprocessRole)).not.toContain('s3:PutObject');
  });

  test('prod RetrievalHealthAlarms stay actionless until the #671 flag is enabled', () => {
    const alarms = template.findResources('AWS::CloudWatch::Alarm');

    const retrievalHealthAlarms = Object.entries(alarms).filter(([id]) =>
      id.includes('RetrievalHealthAlarms'),
    );
    expect(retrievalHealthAlarms).toHaveLength(4);
    for (const [, alarm] of retrievalHealthAlarms) {
      expect((alarm as any).Properties.Namespace).toBe('Renate/Prod/Retrieval');
      // #668/#671: no SNS action until a fresh prod health state is verified.
      expect((alarm as any).Properties.AlarmActions).toBeUndefined();
    }

    const etlAlarms = Object.entries(alarms).filter(([id]) =>
      id.includes('EtlAlarms'),
    );
    expect(etlAlarms.length).toBeGreaterThan(0);
    for (const [, alarm] of etlAlarms) {
      const actions = (alarm as any).Properties.AlarmActions;
      expect(Array.isArray(actions)).toBe(true);
      expect(actions.length).toBeGreaterThan(0);
    }
  });

  test('the #671 flag wires all four prod RetrievalHealthAlarms to SNS', () => {
    const enabledTemplate = buildProdFoundationTemplate(true);
    const alarms = enabledTemplate.findResources('AWS::CloudWatch::Alarm');
    const retrievalHealthAlarms = Object.entries(alarms).filter(([id]) =>
      id.includes('RetrievalHealthAlarms'),
    );

    expect(retrievalHealthAlarms).toHaveLength(4);
    for (const [, alarm] of retrievalHealthAlarms) {
      const actions = (alarm as any).Properties.AlarmActions;
      expect(Array.isArray(actions)).toBe(true);
      expect(actions).toHaveLength(1);
    }
  });

  test('requires an explicit candidate slot', () => {
    const digest = `sha256:${'c'.repeat(64)}`;
    const app = new App({
      context: {
        etlImageTag: digest,
        blueEtlImageTag: digest,
        greenEtlImageTag: digest,
      },
    });
    expect(
      () =>
        new EtlKnowledgeBaseStack(app, 'MissingProdCandidateSlot', {
          envName: 'prod',
          kbStackName: 'renate-etl-kb-prod',
          kbDescription: 'Test prod KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '718036735727', region: 'eu-central-1' },
        }),
    ).toThrow(/retrievalCandidateSlot=blue\|green/);
  });

  test('requires an explicit immutable ETL image coordinate', () => {
    const digest = `sha256:${'c'.repeat(64)}`;
    const app = new App({
      context: {
        retrievalCandidateSlot: 'blue',
        blueEtlImageTag: digest,
        greenEtlImageTag: digest,
      },
    });
    expect(
      () =>
        new EtlKnowledgeBaseStack(app, 'MissingProdEtlImageTag', {
          envName: 'prod',
          kbStackName: 'renate-etl-kb-prod',
          kbDescription: 'Test prod KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '718036735727', region: 'eu-central-1' },
        }),
    ).toThrow(/etlImageTag not provided for env "prod"/);
  });

  test('requires immutable image coordinates for both slot builders', () => {
    const digest = `sha256:${'c'.repeat(64)}`;
    const app = new App({
      context: {
        etlImageTag: digest,
        retrievalCandidateSlot: 'blue',
        blueEtlImageTag: digest,
      },
    });
    expect(
      () =>
        new EtlKnowledgeBaseStack(app, 'MissingProdGreenImageTag', {
          envName: 'prod',
          kbStackName: 'renate-etl-kb-prod',
          kbDescription: 'Test prod KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '718036735727', region: 'eu-central-1' },
        }),
    ).toThrow(/requires immutable blueEtlImageTag and greenEtlImageTag/);
  });

  test('requires the selected slot image to equal etlImageTag', () => {
    const digest = `sha256:${'c'.repeat(64)}`;
    const other = `sha256:${'d'.repeat(64)}`;
    const app = new App({
      context: {
        etlImageTag: digest,
        retrievalCandidateSlot: 'blue',
        blueEtlImageTag: other,
        greenEtlImageTag: digest,
      },
    });
    expect(
      () =>
        new EtlKnowledgeBaseStack(app, 'MismatchedProdCandidateImage', {
          envName: 'prod',
          kbStackName: 'renate-etl-kb-prod',
          kbDescription: 'Test prod KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '718036735727', region: 'eu-central-1' },
        }),
    ).toThrow(/must equal blueEtlImageTag/);
  });
});

describe('#489 — release retention lifecycle', () => {
  test('dev source bucket expires only explicitly unpinned releases after 90 days', () => {
    const template = buildTemplate();
    template.hasResourceProperties('AWS::S3::Bucket', {
      VersioningConfiguration: Match.absent(),
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            Id: 'RawRelease-Releases-ExpireUnpinned',
            Status: 'Enabled',
            ExpirationInDays: 90,
            Prefix: 'releases/',
            TagFilters: [{ Key: 'renate:retention', Value: 'unpinned' }],
          }),
        ]),
      },
    });
  });

  test('QA blue and green processed buckets share retention, with version cleanup only on green', () => {
    const template = buildQaFoundationTemplate();
    const buckets = template.findResources('AWS::S3::Bucket');
    const blue = Object.entries(buckets).find(([id]) =>
      id.startsWith('IngestionBucket'),
    )?.[1] as any;
    const green = Object.entries(buckets).find(([id]) =>
      id.startsWith('GreenProcessedBucket'),
    )?.[1] as any;

    expect(blue).toBeDefined();
    expect(green).toBeDefined();
    expect(blue.Properties.VersioningConfiguration).toBeUndefined();
    expect(green.Properties.VersioningConfiguration).toEqual({
      Status: 'Enabled',
    });

    for (const bucket of [blue, green]) {
      expect(bucket.Properties.LifecycleConfiguration.Rules).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            ExpirationInDays: 90,
            Prefix: 'processed/releases/',
            TagFilters: [{ Key: 'renate:retention', Value: 'unpinned' }],
          }),
          expect.objectContaining({
            ExpirationInDays: 90,
            Prefix: 'bm25_index/releases/',
            TagFilters: [{ Key: 'renate:retention', Value: 'unpinned' }],
          }),
          expect.objectContaining({
            ExpirationInDays: 90,
            Prefix: 'retrieval-manifests/releases/',
            TagFilters: [{ Key: 'renate:retention', Value: 'unpinned' }],
          }),
        ]),
      );
    }

    expect(
      blue.Properties.LifecycleConfiguration.Rules.some(
        (rule: any) => rule.NoncurrentVersionExpiration !== undefined,
      ),
    ).toBe(false);
    expect(green.Properties.LifecycleConfiguration.Rules).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          NoncurrentVersionExpiration: { NoncurrentDays: 1 },
        }),
        expect.objectContaining({
          ExpiredObjectDeleteMarker: true,
          Prefix: 'processed/releases/',
        }),
        expect.objectContaining({
          ExpiredObjectDeleteMarker: true,
          Prefix: 'bm25_index/releases/',
        }),
        expect.objectContaining({
          ExpiredObjectDeleteMarker: true,
          Prefix: 'retrieval-manifests/releases/',
        }),
      ]),
    );
  });
});

describe('EtlKnowledgeBaseStack — #487/#488 assertions', () => {
  let templateNoSeeding: Template;

  beforeAll(() => {
    templateNoSeeding = buildTemplate();
  });

  describe('EtlSourceBucketNameParameter', () => {
    test('synthesizes the SSM parameter for the ETL source bucket name', () => {
      templateNoSeeding.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/etl-source-bucket-name',
        Type: 'String',
        Description:
          'ETL source bucket name for versioned data-artifact uploads',
      });
    });

    test('SSM parameter value references the source bucket (resolved token)', () => {
      const params = templateNoSeeding.findResources('AWS::SSM::Parameter', {
        Properties: { Name: '/dev/renate/etl-source-bucket-name' },
      });
      const values = Object.values(params).map((r: any) => r.Properties.Value);
      expect(values.length).toBe(1);
      expect(typeof values[0] === 'object').toBe(true);
    });
  });

  describe('Source bucket S3 notification — no key filter', () => {
    test('OBJECT_CREATED SQS notification for TransformPipeline carries no filter rules', () => {
      const notifications = templateNoSeeding.findResources(
        'Custom::S3BucketNotifications',
      );

      const allQueueConfigs = Object.values(notifications).flatMap((n: any) => {
        const cfg = n.Properties?.NotificationConfiguration;
        return cfg?.QueueConfigurations ?? [];
      });

      const objectCreatedConfigs = allQueueConfigs.filter((q: any) =>
        (q.Events ?? []).includes('s3:ObjectCreated:*'),
      );

      expect(objectCreatedConfigs.length).toBeGreaterThan(0);

      const transformObjectCreatedConfigs = objectCreatedConfigs.filter(
        (q: any) => {
          const queueLogicalId = q.QueueArn?.['Fn::GetAtt']?.[0];
          return (
            typeof queueLogicalId === 'string' &&
            queueLogicalId.startsWith('TransformPipelineProcessingQueue')
          );
        },
      );

      expect(transformObjectCreatedConfigs).toHaveLength(1);

      const withFilter = transformObjectCreatedConfigs.filter(
        (q: any) => q.Filter !== undefined && q.Filter !== null,
      );
      expect(withFilter).toHaveLength(0);
    });
  });

  describe('#488 — no BucketDeployment', () => {
    test('synthesized template contains no Custom::CDKBucketDeployment', () => {
      const bucketDeployments = templateNoSeeding.findResources(
        'Custom::CDKBucketDeployment',
      );
      expect(Object.keys(bucketDeployments)).toHaveLength(0);
    });

    test('synthesized template contains no deploy-time FAQ seeder resources', () => {
      const templateJson = JSON.stringify(templateNoSeeding.toJSON());

      expect(templateJson).not.toContain('HttpSeeder');
      expect(templateJson).not.toContain('http-seeder');
      expect(templateJson).not.toContain('SeedData');
    });
  });

  describe('#488 — no deploy-time BM25 custom resource', () => {
    test('no custom resource with TokenizerVersion property exists', () => {
      const allCr = {
        ...templateNoSeeding.findResources(
          'AWS::CloudFormation::CustomResource',
        ),
        ...templateNoSeeding.findResources('Custom::AWSCDK-custom-resources'),
      };
      const withTokenizer = Object.values(allCr).filter(
        (r: any) => r.Properties?.TokenizerVersion !== undefined,
      );
      expect(withTokenizer).toHaveLength(0);
    });
  });

  describe('#488 — BM25 SQS rebuild notifications remain', () => {
    test('docs/*.md ObjectCreated notification remains', () => {
      const notifications = templateNoSeeding.findResources(
        'Custom::S3BucketNotifications',
      );
      const allQueueConfigs = Object.values(notifications).flatMap((n: any) => {
        const cfg = n.Properties?.NotificationConfiguration;
        return cfg?.QueueConfigurations ?? [];
      });

      const mdCreatedConfigs = allQueueConfigs.filter(
        (q: any) =>
          (q.Events ?? []).includes('s3:ObjectCreated:*') &&
          q.Filter?.Key?.FilterRules?.some(
            (r: any) => r.Name === 'suffix' && r.Value === '.md',
          ),
      );
      expect(mdCreatedConfigs.length).toBeGreaterThan(0);
    });

    test('docs/*.md ObjectRemoved notification remains', () => {
      const notifications = templateNoSeeding.findResources(
        'Custom::S3BucketNotifications',
      );
      const allQueueConfigs = Object.values(notifications).flatMap((n: any) => {
        const cfg = n.Properties?.NotificationConfiguration;
        return cfg?.QueueConfigurations ?? [];
      });

      const mdRemovedConfigs = allQueueConfigs.filter(
        (q: any) =>
          (q.Events ?? []).includes('s3:ObjectRemoved:*') &&
          q.Filter?.Key?.FilterRules?.some(
            (r: any) => r.Name === 'suffix' && r.Value === '.md',
          ),
      );
      expect(mdRemovedConfigs.length).toBeGreaterThan(0);
    });
  });

  describe('#488 — bm25-builder-function-name SSM parameter', () => {
    test('synthesizes the SSM parameter for the BM25 builder function name', () => {
      templateNoSeeding.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/bm25-builder-function-name',
        Type: 'String',
        Description:
          'BM25 index builder Lambda function name for operator rebuilds',
      });
    });
  });

  describe('#488 — data-artifact-version is NOT synthesized (CI-owned)', () => {
    test('no AWS::SSM::Parameter for data-artifact-version exists in the template', () => {
      const params = templateNoSeeding.findResources('AWS::SSM::Parameter', {
        Properties: {
          Name: Match.stringLikeRegexp('data-artifact-version'),
        },
      });
      expect(Object.keys(params)).toHaveLength(0);

      const templateParameters = templateNoSeeding.toJSON().Parameters ?? {};
      const dataVersionLookups = Object.values(templateParameters).filter(
        (parameter: any) =>
          parameter.Type === 'AWS::SSM::Parameter::Value<String>' &&
          parameter.Default === '/dev/renate/data-artifact-version',
      );
      expect(dataVersionLookups).toHaveLength(0);
    });
  });

  describe('#488 — active-version reprocess trigger', () => {
    test('synthesizes a custom resource with active-version Sources entry', () => {
      const allCr = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );

      const reprocessCrs = Object.values(allCr).filter((r: any) => {
        const sources: any[] = r.Properties?.Sources ?? [];
        return sources.some((s: any) => s.Type === 'active-version');
      });

      expect(reprocessCrs.length).toBeGreaterThan(0);
    });

    test('active-version entry has VersionParameterName, ReleaseBasePrefix, and XML+MD+PDF suffixes', () => {
      const allCr = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );

      let found = false;
      for (const r of Object.values(allCr) as any[]) {
        const sources: any[] = r.Properties?.Sources ?? [];
        const activeEntry = sources.find(
          (s: any) => s.Type === 'active-version',
        );
        if (activeEntry) {
          expect(activeEntry.VersionParameterName).toBe(
            '/dev/renate/data-artifact-version',
          );
          expect(activeEntry.ReleaseBasePrefix).toBe('releases/');
          expect(activeEntry.Suffixes).toEqual(
            expect.arrayContaining(['.xml', '.md', '.pdf']),
          );
          found = true;
          break;
        }
      }
      expect(found).toBe(true);
    });

    test('reprocess role has ssm:GetParameter scoped to the exact version parameter ARN', () => {
      // Resource must be the data-artifact-version parameter ARN, not a wildcard.
      const roles = templateNoSeeding.findResources('AWS::IAM::Role');

      const ssmStatements: any[] = [];
      for (const role of Object.values(roles) as any[]) {
        for (const policy of role.Properties?.Policies ?? []) {
          for (const stmt of policy.PolicyDocument?.Statement ?? []) {
            if (JSON.stringify(stmt.Action).includes('ssm:GetParameter')) {
              ssmStatements.push(stmt);
            }
          }
        }
      }

      expect(ssmStatements.length).toBeGreaterThan(0);
      for (const stmt of ssmStatements) {
        expect(stmt.Effect).toBe('Allow');
        const resourceStr = JSON.stringify(stmt.Resource);
        expect(resourceStr).not.toContain('parameter/*');
        expect(stmt.Resource).not.toBe('*');
      }
      const allResources = ssmStatements
        .map((s) => JSON.stringify(s.Resource))
        .join(' ');
      expect(allResources).toContain(
        ':parameter/dev/renate/data-artifact-version',
      );
      expect(allResources).toContain(
        ':parameter/dev/renate/faq-artifact-version',
      );
    });
  });

  describe('#591 — deploy-time FAQ seeder and static source removed', () => {
    test('active FAQ entry remains present with the strict versioned prefix', () => {
      const allCr = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      const entries = Object.values(allCr).flatMap(
        (resource: any) => resource.Properties?.Sources ?? [],
      );
      expect(entries).toContainEqual({
        Type: 'active-faq',
        VersionParameterName: '/dev/renate/faq-artifact-version',
        ReleaseBasePrefix: 'releases/faq/',
        SubPrefix: 'html/',
        Suffixes: ['.html'],
      });
    });

    test('FAQ pointer remains a runtime-only lookup on first deployment', () => {
      const parameters = templateNoSeeding.toJSON().Parameters ?? {};

      expect(Object.values(parameters)).not.toContainEqual({
        Type: 'AWS::SSM::Parameter::Value<String>',
        Default: '/dev/renate/faq-artifact-version',
      });
    });

    test('no static source remains in reprocess trigger Sources', () => {
      const allCr = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );

      for (const r of Object.values(allCr) as any[]) {
        const sources: any[] = r.Properties?.Sources ?? [];
        const staticEntries = sources.filter((s: any) => s.Type === 'static');
        expect(staticEntries).toHaveLength(0);
      }
    });

    test('reprocess trigger contains exactly active brochure and active FAQ sources', () => {
      const allCr = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );

      for (const r of Object.values(allCr) as any[]) {
        const sources: any[] = r.Properties?.Sources ?? [];
        if (sources.some((s: any) => s.Type === 'active-version')) {
          expect(sources.map((source: any) => source.Type)).toEqual([
            'active-version',
            'active-faq',
          ]);
          return;
        }
      }

      throw new Error('SourceReprocessTrigger custom resource not found');
    });

    test('dev reprocess trigger preserves replay-on-deploy readiness contract', () => {
      const resources = templateNoSeeding.findResources(
        'AWS::CloudFormation::CustomResource',
      );
      const reprocess = Object.values(resources).find((resource: any) =>
        (resource.Properties?.Sources ?? []).some(
          (source: any) => source.Type === 'active-version',
        ),
      ) as any;

      expect(reprocess).toBeDefined();
      expect(reprocess.Properties.RuntimeIdentity).toBeUndefined();
    });
  });

  describe('#590 — ETL Lambdas reference the renate-etl-lambda ECR image', () => {
    test('Transform, Chunking (when enabled), and BM25 Lambdas use Code.ImageUri referencing renate-etl-lambda', () => {
      const templateWithChunking = buildTemplateWithChunking();
      const lambdas = templateWithChunking.findResources(
        'AWS::Lambda::Function',
      );
      const ecrBacked = Object.values(lambdas).filter((r: any) => {
        const uri = r.Properties?.Code?.ImageUri;
        return uri && JSON.stringify(uri).includes('renate-etl-lambda');
      });
      expect(ecrBacked.length).toBeGreaterThanOrEqual(3);
    });

    test('BM25 builder keeps ImageConfig.Command = etl.bm25_index_builder.handler', () => {
      templateNoSeeding.hasResourceProperties('AWS::Lambda::Function', {
        ImageConfig: Match.objectLike({
          Command: ['etl.bm25_index_builder.handler'],
        }),
      });
    });

    test('Transform/Chunking Lambdas have no ImageConfig.Command override (inherit Dockerfile default)', () => {
      const templateWithChunking = buildTemplateWithChunking();
      const lambdas = templateWithChunking.findResources(
        'AWS::Lambda::Function',
      );
      const ecrBackedWithoutCommand = Object.values(lambdas).filter(
        (r: any) => {
          const uri = r.Properties?.Code?.ImageUri;
          const isEcrBacked =
            uri && JSON.stringify(uri).includes('renate-etl-lambda');
          return isEcrBacked && r.Properties?.ImageConfig === undefined;
        },
      );
      expect(ecrBackedWithoutCommand.length).toBeGreaterThanOrEqual(2);
    });

    test('no fromImageAsset local Docker build (dockerfile) metadata remains for ETL Lambdas', () => {
      const assembly = JSON.stringify(templateNoSeeding.toJSON());
      expect(assembly).not.toContain('dockerfile');
    });
  });

  describe('#590 — readiness-gate SSM coordinates', () => {
    test('publishes bm25-rebuild-queue-arn and bm25-rebuild-dlq-arn', () => {
      templateNoSeeding.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/bm25-rebuild-queue-arn',
        Type: 'String',
      });
      templateNoSeeding.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/bm25-rebuild-dlq-arn',
        Type: 'String',
      });
    });

    test('publishes data-source-id', () => {
      templateNoSeeding.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/data-source-id',
        Type: 'String',
      });
    });

    test('chunking disabled (dev default): no chunking-queue-arn/chunking-dlq-arn parameters', () => {
      const params = templateNoSeeding.findResources('AWS::SSM::Parameter', {
        Properties: { Name: Match.stringLikeRegexp('chunking-.*-arn') },
      });
      expect(Object.keys(params)).toHaveLength(0);
    });

    test('chunking enabled: publishes chunking-queue-arn and chunking-dlq-arn', () => {
      const templateWithChunking = buildTemplateWithChunking();
      templateWithChunking.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/chunking-queue-arn',
        Type: 'String',
      });
      templateWithChunking.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/dev/renate/chunking-dlq-arn',
        Type: 'String',
      });
    });
  });

  describe('#590 fix — etlImageTag context override', () => {
    function buildStackWithContext(
      envName: string,
      etlImageTagContext?: string,
    ): () => Template {
      return () => {
        const context: Record<string, string> = {};
        if (etlImageTagContext) {
          context.etlImageTag = etlImageTagContext;
        }
        if (envName === 'qa' || envName === 'preprod') {
          context.retrievalCandidateSlot =
            envName === 'preprod' ? 'blue' : 'green';
          context.blueEtlImageTag =
            envName === 'preprod'
              ? (etlImageTagContext ?? 'v1.84.0')
              : 'v1.83.3-qa-blue-baseline';
          context.greenEtlImageTag = etlImageTagContext ?? 'v1.84.0';
        }
        const app = new App({ context });
        const stack = new EtlKnowledgeBaseStack(app, 'TestEtlKbStackCtx', {
          envName,
          kbStackName: `renate-etl-kb-${envName}`,
          kbDescription: 'Test KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '123456789012', region: 'eu-central-1' },
        });
        return Template.fromStack(stack);
      };
    }

    test('valid v<semver> context override synthesizes without needing SSM (non-dev)', () => {
      const build = buildStackWithContext('qa', 'v1.84.0');
      expect(build).not.toThrow();
      const template = build();
      const lambdas = template.findResources('AWS::Lambda::Function');
      const ecrBacked = Object.values(lambdas).filter((r: any) => {
        const uri = r.Properties?.Code?.ImageUri;
        return uri && JSON.stringify(uri).includes('renate-etl-lambda');
      });
      expect(ecrBacked.length).toBeGreaterThanOrEqual(2);
      const reprocess = Object.values(
        template.findResources('AWS::CloudFormation::CustomResource'),
      ).find((resource: any) =>
        (resource.Properties?.Sources ?? []).some(
          (source: any) => source.Type === 'active-version',
        ),
      );
      expect(reprocess).toBeUndefined();
    });

    test('legacy git-<sha> context override remains valid for rollback', () => {
      const build = buildStackWithContext(
        'qa',
        'git-abc1234def5678901234567890123456789012',
      );
      expect(build).not.toThrow();
    });

    test('valid sha256:<digest> context override synthesizes', () => {
      const build = buildStackWithContext(
        'preprod',
        `sha256:${'a'.repeat(64)}`,
      );
      expect(build).not.toThrow();
    });

    test('preprod foundation can preserve the exact legacy CDK asset repository and tag', () => {
      const assetTag = 'a'.repeat(64);
      const repository =
        'cdk-hnb659fds-container-assets-271033482134-eu-central-1';
      const app = new App({
        context: {
          etlImageRepository: repository,
          etlImageTag: assetTag,
          retrievalCandidateSlot: 'blue',
          blueEtlImageTag: assetTag,
          greenEtlImageTag: assetTag,
        },
      });
      const stack = new EtlKnowledgeBaseStack(
        app,
        'PreprodLegacyAssetRepository',
        {
          envName: 'preprod',
          kbStackName: 'renate-etl-kb-preprod',
          kbDescription: 'Test KB stack',
          vectorDimension: 1024,
          etlConfig: minimalEtlConfig,
          etlEcrAccount: '831926590742',
          env: { account: '271033482134', region: 'eu-central-1' },
        },
      );
      const assembly = JSON.stringify(Template.fromStack(stack).toJSON());
      expect(assembly).toContain(repository);
      expect(assembly).toContain(assetTag);
    });

    test('legacy CDK asset repository override is rejected outside preprod', () => {
      const assetTag = 'a'.repeat(64);
      const app = new App({
        context: {
          etlImageRepository:
            'cdk-hnb659fds-container-assets-123456789012-eu-central-1',
          etlImageTag: assetTag,
          retrievalCandidateSlot: 'green',
          blueEtlImageTag: assetTag,
          greenEtlImageTag: assetTag,
        },
      });
      expect(
        () =>
          new EtlKnowledgeBaseStack(app, 'QaLegacyAssetRepository', {
            envName: 'qa',
            kbStackName: 'renate-etl-kb-qa',
            kbDescription: 'Test KB stack',
            vectorDimension: 1024,
            etlConfig: minimalEtlConfig,
            etlEcrAccount: '831926590742',
            env: { account: '123456789012', region: 'eu-central-1' },
          }),
      ).toThrow(/only select the exact preprod CDK bootstrap asset repository/);
    });

    test('mutable "latest" tag context override is rejected at synth time', () => {
      const build = buildStackWithContext('qa', 'latest');
      expect(build).toThrow(/mutable tags/i);
    });

    test('arbitrary non-immutable-format context override is rejected', () => {
      const build = buildStackWithContext('qa', 'release-1.2.3');
      expect(build).toThrow(/Invalid etlImageTag/i);
    });

    test('non-dev env without context override and without SSM value throws a clear error', () => {
      const build = buildStackWithContext('qa');
      expect(build).toThrow(/etlImageTag not provided for env "qa"/);
    });

    test('dev env without context override falls back to SSM (no throw)', () => {
      const build = buildStackWithContext('dev');
      expect(build).not.toThrow();
    });

    test('dev env WITH a valid context override uses the override, not SSM', () => {
      // Both paths are valid for dev; context takes priority per spec D4.
      const build = buildStackWithContext('dev', 'v3.4.5');
      expect(build).not.toThrow();
      const template = build();
      const assembly = JSON.stringify(template.toJSON());
      // The override tag should appear literally in the synthesized ImageUri.
      expect(assembly).toContain('v3.4.5');
    });

    test('QA requires an explicit candidate slot', () => {
      const app = new App({
        context: {
          etlImageTag: 'v1.84.0',
          blueEtlImageTag: 'v1.83.3',
          greenEtlImageTag: 'v1.84.0',
        },
      });
      expect(
        () =>
          new EtlKnowledgeBaseStack(app, 'MissingQaCandidateSlot', {
            envName: 'qa',
            kbStackName: 'renate-etl-kb-qa',
            kbDescription: 'Test KB stack',
            vectorDimension: 1024,
            etlConfig: minimalEtlConfig,
            etlEcrAccount: '831926590742',
            env: { account: '123456789012', region: 'eu-central-1' },
          }),
      ).toThrow(/retrievalCandidateSlot=blue\|green/);
    });

    test('preprod also requires an explicit candidate slot', () => {
      const digest = `sha256:${'b'.repeat(64)}`;
      const app = new App({
        context: {
          etlImageTag: digest,
          blueEtlImageTag: digest,
          greenEtlImageTag: digest,
        },
      });
      expect(
        () =>
          new EtlKnowledgeBaseStack(app, 'MissingPreprodCandidateSlot', {
            envName: 'preprod',
            kbStackName: 'renate-etl-kb-preprod',
            kbDescription: 'Test KB stack',
            vectorDimension: 1024,
            etlConfig: minimalEtlConfig,
            etlEcrAccount: '831926590742',
            env: { account: '271033482134', region: 'eu-central-1' },
          }),
      ).toThrow(/retrievalCandidateSlot=blue\|green/);
    });

    test('QA requires the selected slot image to equal etlImageTag', () => {
      const app = new App({
        context: {
          etlImageTag: 'v1.84.0',
          retrievalCandidateSlot: 'blue',
          blueEtlImageTag: 'v1.83.3',
          greenEtlImageTag: 'v1.84.0',
        },
      });
      expect(
        () =>
          new EtlKnowledgeBaseStack(app, 'MismatchedQaCandidateImage', {
            envName: 'qa',
            kbStackName: 'renate-etl-kb-qa',
            kbDescription: 'Test KB stack',
            vectorDimension: 1024,
            etlConfig: minimalEtlConfig,
            etlEcrAccount: '831926590742',
            env: { account: '123456789012', region: 'eu-central-1' },
          }),
      ).toThrow(/must equal blueEtlImageTag/);
    });
  });
});

describe('#494/#643/#668 — RetrievalHealthAlarms are manifest-managed only', () => {
  test('dev stack synthesizes without retrieval-health alarms or heartbeat', () => {
    const template = buildTemplate();
    const alarms = template.findResources('AWS::CloudWatch::Alarm');
    const alarmNames = Object.values(alarms).map(
      (a: any) => a.Properties?.AlarmName,
    );
    // CheckExecutedAlarm treats missing data as BREACHING, so environments that
    // are not manifest-managed and have no health-check pipeline must not create
    // these alarms.
    expect(
      alarmNames.some((n: string) =>
        n?.includes('retrieval-check-executed-heartbeat'),
      ),
    ).toBe(false);
    expect(
      alarmNames.some((n: string) =>
        n?.includes('retrieval-ingestion-failure'),
      ),
    ).toBe(false);
    expect(
      alarmNames.some((n: string) =>
        n?.includes('retrieval-coherence-failure'),
      ),
    ).toBe(false);
    expect(
      alarmNames.some((n: string) =>
        n?.includes('retrieval-retention-pin-missing'),
      ),
    ).toBe(false);

    const dashboardAlarms = template.findResources('AWS::CloudWatch::Alarm', {
      Properties: { Namespace: 'Renate/QA/Retrieval' },
    });
    expect(Object.keys(dashboardAlarms)).toHaveLength(0);
  });

  test('qa stack synthesizes all four RetrievalHealthAlarms', () => {
    const template = buildQaFoundationTemplate();
    const alarms = template.findResources('AWS::CloudWatch::Alarm', {
      Properties: { Namespace: 'Renate/QA/Retrieval' },
    });
    expect(Object.keys(alarms)).toHaveLength(4);
  });
});
