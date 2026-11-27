import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct, DependencyGroup } from 'constructs';
import * as path from 'path';

import { ConfigurationBuilder } from './utils/config-builder';
import { fingerprintSources, fingerprintFiles } from './utils/fingerprint';
import { S3ToS3VectorsKnowledgeBase } from './constructs/knowledge-base/s3-to-s3-vectors-knowledge-base';
import { KbSyncTrigger } from './constructs/knowledge-base/kb-sync-trigger';
import { EtlAlarms } from './constructs/knowledge-base/etl-alarms';
import { TransformPipeline } from './constructs/knowledge-base/transform-pipeline';
import { CustomChunkingPipeline } from './constructs/knowledge-base/custom-chunking-pipeline';
import { Bm25IndexBuilder } from './constructs/knowledge-base/bm25-index-builder';
import {
  SourceReprocessTrigger,
  ReprocessSource,
  ActiveFaqReprocessSource,
} from './constructs/knowledge-base/source-reprocess-trigger';
import { S3Factory } from './factories/s3-factory';
import { DeletionBehavior } from './interfaces/common';
import { EtlConfig } from './config/kb/etl-config';
import { AlertingTopic } from './constructs/monitoring/alerting-topic';
import { RetrievalHealthAlarms } from './constructs/monitoring/retrieval-health-alarms';
import {
  unversionedReleaseRetentionRules,
  versionedReleaseRetentionRules,
} from './utils/release-retention';
import {
  isManifestManagedEnvironment,
  retrievalMetricNamespace,
} from './config/retrieval-environment';

const RETRIEVAL_RELEASE_PREFIXES = [
  'processed/releases/',
  'bm25_index/releases/',
  'retrieval-manifests/releases/',
];

export interface EtlKnowledgeBaseStackProps extends cdk.StackProps {
  readonly envName: string;
  readonly kbStackName: string;
  readonly kbDescription: string;
  readonly vectorDimension: number;
  readonly etlConfig: EtlConfig;
  /** Legacy single recipient. */
  readonly alertEmail?: string;
  readonly alertEmails?: string[];
  /** Prod retrieval-health SNS actions gate (#671 heartbeat verification). */
  readonly retrievalHealthAlarmActionsEnabled?: boolean;
  /** ECR account for renate-etl-lambda (always dev account). */
  readonly etlEcrAccount: string;
}

/** Bedrock Knowledge Base + ETL pre-processing (DITA → HTML → Markdown → KB ingest). */
export class EtlKnowledgeBaseStack extends cdk.Stack {
  public readonly ingestionBucket: s3.IBucket;
  public readonly knowledgeBaseId: string;
  public readonly greenIngestionBucket?: s3.IBucket;
  public readonly greenKnowledgeBaseId?: string;

  public readonly sourceBucket: s3.IBucket;
  public readonly transformPipeline: TransformPipeline;
  public readonly sourceReprocessTrigger?: SourceReprocessTrigger;
  public readonly bm25BuilderLambda: lambda.DockerImageFunction;
  public readonly bm25RebuildQueue: sqs.Queue;
  public readonly bm25RebuildDlq: sqs.Queue;
  public greenBm25BuilderLambda?: lambda.DockerImageFunction;
  public greenBm25RebuildDlq?: sqs.Queue;

  constructor(scope: Construct, id: string, props: EtlKnowledgeBaseStackProps) {
    super(scope, id, props);

    const {
      envName,
      kbStackName,
      vectorDimension,
      etlConfig,
      alertEmail,
      etlEcrAccount,
    } = props;
    const manifestManaged = isManifestManagedEnvironment(envName);
    // Preprod/prod suffix green resources physically (they migrated from a
    // legacy blue predating the green split). QA uses default naming. Blue
    // identities stay untouched everywhere.
    const greenPhysicalNameEnvironment =
      envName === 'preprod' || envName === 'prod' ? envName : undefined;
    // Explicit prod branch (Prod* retention rule IDs) avoids falling through
    // to the preprod default (#668). Only reached under manifestManaged.
    const retentionIdPrefix =
      envName === 'qa' ? 'Qa' : envName === 'prod' ? 'Prod' : 'Preprod';
    // Preserve historical QA-labelled output descriptions on qa/preprod; prod gets accurate label.
    const greenOutputEnvironmentLabel = envName === 'prod' ? 'Prod' : 'QA';

    const kbConfiguration = ConfigurationBuilder.buildKnowledgeBaseConfig(
      this,
      {
        namePrefix: kbStackName.toLowerCase(),
        embeddingModel: 'amazon.titan-embed-text-v2:0',
        ...(vectorDimension !== undefined && {
          vectorDimension: vectorDimension,
        }),
        inclusionPrefixes: ['docs/'],
        useFoundationParsing: false,
      },
    );

    ConfigurationBuilder.validate(kbConfiguration);

    const knowledgeBase = new S3ToS3VectorsKnowledgeBase(this, 'BedrockKB', {
      configuration: kbConfiguration,
      ...(manifestManaged && {
        ingestionBucketLifecycleRules: unversionedReleaseRetentionRules(
          `${retentionIdPrefix}BlueRetrieval`,
          RETRIEVAL_RELEASE_PREFIXES,
        ),
      }),
    });

    this.ingestionBucket = knowledgeBase.ingestionBucket;
    this.knowledgeBaseId = knowledgeBase.knowledgeBaseId;

    // SSM is the coupling point so ChatbotStack can deploy independently.
    new ssm.StringParameter(this, 'KnowledgeBaseIdParameter', {
      parameterName: `/${envName}/renate/knowledge-base-id`,
      stringValue: knowledgeBase.knowledgeBaseId,
      description: 'Bedrock Knowledge Base ID for cross-stack lookups',
    });

    const kbSyncTrigger = new KbSyncTrigger(this, 'KbSyncTrigger', {
      ingestionBucket: knowledgeBase.ingestionBucket,
      knowledgeBaseId: knowledgeBase.knowledgeBaseId,
      dataSourceId: knowledgeBase.dataSourceId,
      prefix: 'docs/',
      suffixes: ['.json'],
    });

    // Green foundation (#491/#641): isolated processed bucket, vector store,
    // KB, data source, sync path. No active-manifest parameter here —
    // foundation deploy must not select green or shift QA behavior.
    let greenKnowledgeBase: S3ToS3VectorsKnowledgeBase | undefined;
    let greenProcessedBucket: s3.IBucket | undefined;
    let greenKbSyncTrigger: KbSyncTrigger | undefined;
    if (manifestManaged) {
      greenProcessedBucket = S3Factory.createBucket(
        this,
        'GreenProcessedBucket',
        {
          environment: envName,
          physicalNameEnvironment: greenPhysicalNameEnvironment,
          purpose: 'retrieval-green-processed',
          versioned: true,
          deletionBehavior: DeletionBehavior.RETAIN,
          enforceSSL: true,
          blockPublicAccess: true,
          lifecycleRules: versionedReleaseRetentionRules(
            `${retentionIdPrefix}GreenRetrieval`,
            RETRIEVAL_RELEASE_PREFIXES,
          ),
        },
      );

      greenKnowledgeBase = new S3ToS3VectorsKnowledgeBase(
        this,
        'GreenBedrockKB',
        {
          configuration: kbConfiguration,
          ingestionBucket: greenProcessedBucket,
          resourceNameSuffix: 'green',
          physicalNameEnvironment: greenPhysicalNameEnvironment,
          // Retain green KB + S3 Vectors on rollback/delete so a foundation
          // mistake cannot destroy live retrieval state (#641/#668).
          ...((envName === 'preprod' || envName === 'prod') && {
            deletionBehavior: 'RETAIN',
            dataDeletionPolicy: 'RETAIN',
          }),
        },
      );
      this.greenIngestionBucket = greenProcessedBucket;
      this.greenKnowledgeBaseId = greenKnowledgeBase.knowledgeBaseId;

      greenKbSyncTrigger = new KbSyncTrigger(this, 'GreenKbSyncTrigger', {
        ingestionBucket: greenProcessedBucket,
        knowledgeBaseId: greenKnowledgeBase.knowledgeBaseId,
        dataSourceId: greenKnowledgeBase.dataSourceId,
        prefix: 'docs/',
        suffixes: ['.json'],
        resourceNameSuffix: 'green',
        physicalNameEnvironment: greenPhysicalNameEnvironment,
      });

      const slotCoordinates = [
        {
          slot: 'blue',
          knowledgeBaseId: knowledgeBase.knowledgeBaseId,
          dataSourceId: knowledgeBase.dataSourceId,
          processedBucketName: knowledgeBase.ingestionBucket.bucketName,
          kbSyncFunctionName: kbSyncTrigger.syncLambda.functionName,
        },
        {
          slot: 'green',
          knowledgeBaseId: greenKnowledgeBase.knowledgeBaseId,
          dataSourceId: greenKnowledgeBase.dataSourceId,
          processedBucketName: greenProcessedBucket.bucketName,
          kbSyncFunctionName: greenKbSyncTrigger.syncLambda.functionName,
        },
      ];

      for (const coordinates of slotCoordinates) {
        const slotId = coordinates.slot === 'blue' ? 'Blue' : 'Green';
        const baseName = `/${envName}/renate/retrieval/slots/${coordinates.slot}`;
        new ssm.StringParameter(this, `${slotId}SlotKnowledgeBaseIdParameter`, {
          parameterName: `${baseName}/knowledge-base-id`,
          stringValue: coordinates.knowledgeBaseId,
          description: `${slotId} retrieval slot Bedrock Knowledge Base ID`,
        });
        new ssm.StringParameter(this, `${slotId}SlotDataSourceIdParameter`, {
          parameterName: `${baseName}/data-source-id`,
          stringValue: coordinates.dataSourceId,
          description: `${slotId} retrieval slot Bedrock data source ID`,
        });
        new ssm.StringParameter(this, `${slotId}SlotProcessedBucketParameter`, {
          parameterName: `${baseName}/processed-bucket-name`,
          stringValue: coordinates.processedBucketName,
          description: `${slotId} retrieval slot processed corpus bucket`,
        });
        new ssm.StringParameter(this, `${slotId}SlotKbSyncFunctionParameter`, {
          parameterName: `${baseName}/kb-sync-function-name`,
          stringValue: coordinates.kbSyncFunctionName,
          description: `${slotId} retrieval slot explicit KB sync function`,
        });
      }
    }

    this.sourceBucket = S3Factory.createBucket(this, 'EtlSourceBucket', {
      environment: envName,
      purpose: 'etl-source',
      versioned: false,
      deletionBehavior: DeletionBehavior.DELETE,
      enforceSSL: true,
      blockPublicAccess: true,
      lifecycleRules:
        envName === 'dev' || manifestManaged
          ? unversionedReleaseRetentionRules('RawRelease', ['releases/'])
          : [],
    });

    // Image is built+pushed by `build-etl-image:dev` CI job, never at synth.
    // CDK references the already-published tag via SSM; missing param fails at CFN.
    // No fallback to a local Docker asset.
    const etlImageRepositoryContext = this.node.tryGetContext(
      'etlImageRepository',
    ) as string | undefined;
    const bootstrapImageRepository = `cdk-hnb659fds-container-assets-${this.account}-${this.region}`;
    if (
      etlImageRepositoryContext &&
      (envName !== 'preprod' ||
        etlImageRepositoryContext !== bootstrapImageRepository)
    ) {
      throw new Error(
        'etlImageRepository may only select the exact preprod CDK bootstrap ' +
          'asset repository during the legacy foundation migration.',
      );
    }
    const etlRepositoryName = etlImageRepositoryContext ?? 'renate-etl-lambda';
    const etlRepositoryAccount = etlImageRepositoryContext
      ? this.account
      : etlEcrAccount;
    const etlRepo = ecr.Repository.fromRepositoryAttributes(
      this,
      'EtlRepository',
      {
        repositoryName: etlRepositoryName,
        repositoryArn: this.formatArn({
          service: 'ecr',
          resource: 'repository',
          resourceName: etlRepositoryName,
          account: etlRepositoryAccount,
        }),
      },
    );

    // Priority: --context etlImageTag (manual, D4) > SSM /${envName}/renate/etl-image-tag
    // (dev auto path, written only by build-etl-image:dev). SSM param is dev-only
    // (#590 scope); qa/preprod/prod MUST pass --context etlImageTag explicitly.
    // Only literal context values are regex-validated here — the SSM value is a
    // token at synth time; its writer owns immutable-tag enforcement.
    const etlImageTagContext = this.node.tryGetContext('etlImageTag') as
      string | undefined;

    const IMMUTABLE_TAG_PATTERN =
      /^(v\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.-]+)?|git-[0-9a-f]{7,40}|sha256:[0-9a-f]{64})$/;
    const LEGACY_CDK_ASSET_TAG_PATTERN = /^[0-9a-f]{64}$/;
    const isImmutableImageCoordinate = (value: string): boolean =>
      IMMUTABLE_TAG_PATTERN.test(value) ||
      (Boolean(etlImageRepositoryContext) &&
        LEGACY_CDK_ASSET_TAG_PATTERN.test(value));

    let etlImageTag: string;
    if (etlImageTagContext) {
      if (!isImmutableImageCoordinate(etlImageTagContext)) {
        throw new Error(
          `Invalid etlImageTag context value "${etlImageTagContext}" — ` +
            'must be an immutable release tag (v<semver>), legacy commit tag ' +
            '(git-<sha>), or ECR digest (sha256:<digest>). Mutable tags such ' +
            'as "latest" are rejected.',
        );
      }
      etlImageTag = etlImageTagContext;
    } else if (envName === 'dev') {
      etlImageTag = ssm.StringParameter.valueForTypedStringParameterV2(
        this,
        `/${envName}/renate/etl-image-tag`,
      );
    } else {
      throw new Error(
        `etlImageTag not provided for env "${envName}". The automatic ` +
          '/dev/renate/etl-image-tag SSM parameter is dev-only (#590 scope) — ' +
          'pass --context etlImageTag=<version-or-digest> explicitly for ' +
          'qa/preprod/prod/demo manual deploys.',
      );
    }

    // Per-slot builder image coordinates: shared transform routes to the
    // explicitly selected inactive slot via etlImageTag; the active slot's
    // builder stays pinned to its own image, not updated as a side effect.
    const retrievalCandidateSlotContext = this.node.tryGetContext(
      'retrievalCandidateSlot',
    ) as string | undefined;
    let retrievalCandidateSlot: 'blue' | 'green' | undefined;
    let blueEtlImageTag = etlImageTag;
    let greenEtlImageTag = etlImageTag;
    if (manifestManaged) {
      if (
        retrievalCandidateSlotContext !== 'blue' &&
        retrievalCandidateSlotContext !== 'green'
      ) {
        throw new Error(
          `Manifest-managed env "${envName}" requires --context ` +
            'retrievalCandidateSlot=blue|green so the ' +
            'shared transform cannot be routed implicitly.',
        );
      }
      retrievalCandidateSlot = retrievalCandidateSlotContext;
      const blueContext = this.node.tryGetContext('blueEtlImageTag') as
        string | undefined;
      const greenContext = this.node.tryGetContext('greenEtlImageTag') as
        string | undefined;
      if (!blueContext || !greenContext) {
        throw new Error(
          `Manifest-managed env "${envName}" requires immutable ` +
            'blueEtlImageTag and greenEtlImageTag contexts.',
        );
      }
      for (const [name, value] of [
        ['blueEtlImageTag', blueContext],
        ['greenEtlImageTag', greenContext],
      ] as const) {
        if (!isImmutableImageCoordinate(value)) {
          throw new Error(`Invalid ${name} context value "${value}".`);
        }
      }
      blueEtlImageTag = blueContext;
      greenEtlImageTag = greenContext;
      const selectedTag =
        retrievalCandidateSlot === 'blue' ? blueEtlImageTag : greenEtlImageTag;
      if (selectedTag !== etlImageTag) {
        throw new Error(
          `etlImageTag ${etlImageTag} must equal ${retrievalCandidateSlot}EtlImageTag ${selectedTag}.`,
        );
      }
    }

    // Transform writes directly to ingestion; chunking.enabled inserts an intermediate bucket + Lambda.
    let transformDestination =
      retrievalCandidateSlot === 'green'
        ? (greenProcessedBucket as s3.IBucket)
        : this.ingestionBucket;

    let chunkingPipeline: CustomChunkingPipeline | undefined;
    if (etlConfig.chunking?.enabled) {
      chunkingPipeline = new CustomChunkingPipeline(this, 'ChunkingPipeline', {
        etlConfig,
        destinationBucket: transformDestination,
        etlRepo,
        etlImageTag,
      });
      transformDestination = chunkingPipeline.intermediateBucket;
    }

    this.transformPipeline = new TransformPipeline(this, 'TransformPipeline', {
      etlConfig,
      sourceBucket: this.sourceBucket,
      destinationBucket: transformDestination,
      etlRepo,
      etlImageTag,
    });

    // Reprocess re-emits source files so Transform/Chunking pick up the latest
    // code. Must run only after the updated Lambdas are live — the pipeline
    // dependency forces CFN to update Lambda code before the trigger fires.
    //
    // Two CI-owned sources: active-release (SSM data-artifact-version, re-emits
    // releases/{v}/*.xml|*.md|*.pdf — .pdf kept so pre-#501 coordinates remain
    // reprocessable under post-#501 images) and active-FAQ (re-emits canonical
    // HTML from releases/faq/<coord>/). CDK imports pointers; CI is sole writer.
    if (envName !== 'qa') {
      const reprocessDependencies = new DependencyGroup(this.transformPipeline);
      if (chunkingPipeline) {
        reprocessDependencies.add(chunkingPipeline);
      }

      // Hash the exact set the ETL Dockerfile COPies+installs so a dep bump
      // (e.g. uv.lock) retriggers reprocess — previously corpus stuck on OLD
      // deps because hash never changed with the image (#590 review fix).
      //
      // Narrower than etl-changed.sh's fingerprint (which also tracks CDK
      // sources per #626) and does NOT normalize release versions, so cog.toml
      // pre_bump_hooks rewriting backend/pyproject.toml + uv.lock make this
      // hash change on every dev deploy — intentional per #626 Out of Scope.
      let etlCodeHash = fingerprintSources(
        path.join(__dirname, '../../backend/src/etl'),
      );
      etlCodeHash = fingerprintSources(
        path.join(__dirname, '../../backend/src/bm25_shared'),
        etlCodeHash,
      );
      etlCodeHash = fingerprintFiles(
        [
          path.join(__dirname, '../../pyproject.toml'),
          path.join(__dirname, '../../uv.lock'),
          path.join(__dirname, '../../backend/pyproject.toml'),
        ],
        etlCodeHash,
      );

      // Runtime-only lookup — CDK import turns these into template params that
      // CFN resolves before the custom resource can handle ParameterNotFound
      // in a fresh env; FAQ pointer would deadlock first deploy (#591).
      const dataArtifactVersionParameterName = `/${envName}/renate/data-artifact-version`;
      const faqArtifactVersionParameterName = `/${envName}/renate/faq-artifact-version`;

      const sources: [ReprocessSource, ...ReprocessSource[]] = [
        {
          type: 'active-version',
          versionParameterName: dataArtifactVersionParameterName,
          releaseBasePrefix: 'releases/',
          suffixes: ['.xml', '.md', '.pdf'],
        },
      ];

      // #591: re-emits releases/faq/<sha256>/html/*.html via the transform pipeline.
      sources.push({
        type: 'active-faq',
        versionParameterName: faqArtifactVersionParameterName,
        releaseBasePrefix: 'releases/faq/',
        subPrefix: 'html/',
        suffixes: ['.html'],
      } satisfies ActiveFaqReprocessSource);

      this.sourceReprocessTrigger = new SourceReprocessTrigger(
        this,
        'SourceReprocessTrigger',
        {
          sourceBucket: this.sourceBucket,
          sources,
          reprocessVersion: etlCodeHash,
          // Preprod/prod keep legacy construct identities but drop replay +
          // source-write perms; dev/demo preserve replay-on-deploy behavior.
          enabled: !manifestManaged,
          dependsOn: reprocessDependencies,
        },
      );
    }

    // Rebuilds: S3 events → SQS debounce → Lambda (deploy-time custom resource removed in #488).
    // Manual rebuild: `make bm25-rebuild ENV=<env>`.
    const bm25IndexBuilder = new Bm25IndexBuilder(this, 'Bm25IndexBuilder', {
      ingestionBucket: knowledgeBase.ingestionBucket,
      etlRepo,
      etlImageTag: blueEtlImageTag,
      ...(manifestManaged && { immutableOnly: true }),
      expectedKnowledgeBaseId: knowledgeBase.knowledgeBaseId,
      expectedDataSourceId: knowledgeBase.dataSourceId,
    });
    this.bm25BuilderLambda = bm25IndexBuilder.builderLambda;
    this.bm25RebuildQueue = bm25IndexBuilder.rebuildQueue;
    this.bm25RebuildDlq = bm25IndexBuilder.rebuildDlq;

    if (manifestManaged && greenKnowledgeBase) {
      const greenBm25IndexBuilder = new Bm25IndexBuilder(
        this,
        'GreenBm25IndexBuilder',
        {
          ingestionBucket: greenKnowledgeBase.ingestionBucket,
          etlRepo,
          etlImageTag: greenEtlImageTag,
          immutableOnly: true,
          expectedKnowledgeBaseId: greenKnowledgeBase.knowledgeBaseId,
          expectedDataSourceId: greenKnowledgeBase.dataSourceId,
        },
      );
      // Exposed for #494 alarm wiring further down, after alertingTopic exists.
      this.greenBm25BuilderLambda = greenBm25IndexBuilder.builderLambda;
      this.greenBm25RebuildDlq = greenBm25IndexBuilder.rebuildDlq;

      const builderCoordinates = [
        {
          slot: 'blue',
          builder: bm25IndexBuilder,
        },
        {
          slot: 'green',
          builder: greenBm25IndexBuilder,
        },
      ];

      for (const coordinates of builderCoordinates) {
        const slotId = coordinates.slot === 'blue' ? 'Blue' : 'Green';
        const baseName = `/${envName}/renate/retrieval/slots/${coordinates.slot}`;
        new ssm.StringParameter(
          this,
          `${slotId}SlotBm25BuilderFunctionNameParameter`,
          {
            parameterName: `${baseName}/bm25-builder-function-name`,
            stringValue: coordinates.builder.builderLambda.functionName,
            description: `${slotId} retrieval slot BM25 builder function`,
          },
        );
        new ssm.StringParameter(
          this,
          `${slotId}SlotBm25RebuildQueueArnParameter`,
          {
            parameterName: `${baseName}/bm25-rebuild-queue-arn`,
            stringValue: coordinates.builder.rebuildQueue.queueArn,
            description: `${slotId} retrieval slot BM25 rebuild queue ARN`,
          },
        );
        new ssm.StringParameter(
          this,
          `${slotId}SlotBm25RebuildDlqArnParameter`,
          {
            parameterName: `${baseName}/bm25-rebuild-dlq-arn`,
            stringValue: coordinates.builder.rebuildDlq.queueArn,
            description: `${slotId} retrieval slot BM25 rebuild DLQ ARN`,
          },
        );
        new ssm.StringParameter(
          this,
          `${slotId}SlotBm25ReleasesPrefixParameter`,
          {
            parameterName: `${baseName}/bm25-releases-prefix`,
            stringValue: 'bm25_index/releases/',
            description: `${slotId} retrieval slot immutable BM25 release prefix`,
          },
        );
      }

      new cdk.CfnOutput(this, 'GreenKnowledgeBaseId', {
        value: greenKnowledgeBase.knowledgeBaseId,
        description: `${greenOutputEnvironmentLabel} green retrieval slot Knowledge Base ID (not active)`,
      });
      new cdk.CfnOutput(this, 'GreenDataSourceId', {
        value: greenKnowledgeBase.dataSourceId,
        description: `${greenOutputEnvironmentLabel} green retrieval slot data source ID (not active)`,
      });
      new cdk.CfnOutput(this, 'GreenProcessedBucketName', {
        value: greenKnowledgeBase.ingestionBucket.bucketName,
        description: `${greenOutputEnvironmentLabel} green retrieval slot processed corpus bucket`,
      });
    }

    // Avoids needing cloudformation:DescribeStacks from `make bm25-rebuild`.
    new ssm.StringParameter(this, 'Bm25BuilderFunctionNameParameter', {
      parameterName: `/${envName}/renate/bm25-builder-function-name`,
      stringValue: bm25IndexBuilder.builderLambda.functionName,
      description:
        'BM25 index builder Lambda function name for operator rebuilds',
    });

    // #494: ARN alongside name so ChatbotStack can fromFunctionArn across stacks.
    new ssm.StringParameter(this, 'Bm25BuilderFunctionArnParameter', {
      parameterName: `/${envName}/renate/bm25-builder-function-arn`,
      stringValue: bm25IndexBuilder.builderLambda.functionArn,
      description: 'BM25 index builder Lambda ARN for the monitoring dashboard',
    });

    // Readiness-gate coordinates for etl-readiness-check.sh.
    new ssm.StringParameter(this, 'Bm25RebuildQueueArnParameter', {
      parameterName: `/${envName}/renate/bm25-rebuild-queue-arn`,
      stringValue: bm25IndexBuilder.rebuildQueue.queueArn,
      description: 'BM25 rebuild queue ARN for the readiness gate',
    });

    new ssm.StringParameter(this, 'Bm25RebuildDlqArnParameter', {
      parameterName: `/${envName}/renate/bm25-rebuild-dlq-arn`,
      stringValue: bm25IndexBuilder.rebuildDlq.queueArn,
      description: 'BM25 rebuild DLQ ARN for the readiness gate',
    });

    if (chunkingPipeline) {
      new ssm.StringParameter(this, 'ChunkingQueueArnParameter', {
        parameterName: `/${envName}/renate/chunking-queue-arn`,
        stringValue: chunkingPipeline.processingQueue.queueArn,
        description:
          'Custom chunking processing queue ARN for the readiness gate (only when chunking enabled)',
      });

      new ssm.StringParameter(this, 'ChunkingDlqArnParameter', {
        parameterName: `/${envName}/renate/chunking-dlq-arn`,
        stringValue: chunkingPipeline.dlq.queueArn,
        description:
          'Custom chunking DLQ ARN for the readiness gate (only when chunking enabled)',
      });
    }

    new ssm.StringParameter(this, 'DataSourceIdParameter', {
      parameterName: `/${envName}/renate/data-source-id`,
      stringValue: knowledgeBase.dataSourceId,
      description:
        'Bedrock Knowledge Base data source ID for the readiness gate (ListIngestionJobs/GetIngestionJob)',
    });

    const alertingTopic =
      alertEmail || props.alertEmails?.length
        ? new AlertingTopic(this, 'AlertingTopic', {
            prefix: kbStackName.toLowerCase(),
            envName,
            alertEmail,
            alertEmails: props.alertEmails,
          })
        : undefined;

    new EtlAlarms(this, 'EtlAlarms', {
      transformLambda: this.transformPipeline.transformLambda,
      dlq: this.transformPipeline.dlq,
      kbSyncLambda: kbSyncTrigger.syncLambda,
      lambdaErrorThreshold: 5,
      lambdaErrorEvaluationPeriods: 1,
      alertTopic: alertingTopic?.topic,
      bm25BuilderLambda: bm25IndexBuilder.builderLambda,
      bm25RebuildDlq: bm25IndexBuilder.rebuildDlq,
      slot: 'blue',
    });

    // Green has its own BM25 builder but shares blue's transform pipeline, so
    // omit transformLambda/dlq here (optional on EtlAlarmsProps) to avoid a
    // duplicate alarm on the same metric. slot: 'green' keeps BM25 alarm names
    // distinct — deterministicName hashes on purpose, not construct path (#494).
    if (this.greenBm25BuilderLambda && this.greenBm25RebuildDlq) {
      new EtlAlarms(this, 'GreenEtlAlarms', {
        alertTopic: alertingTopic?.topic,
        bm25BuilderLambda: this.greenBm25BuilderLambda,
        bm25RebuildDlq: this.greenBm25RebuildDlq,
        slot: 'green',
        physicalNameEnvironment: greenPhysicalNameEnvironment,
      });
    }

    // Scheduled retrieval-health alarms (Renate/<Env>/Retrieval). Manifest-
    // managed envs only — dev/demo have no schedule, so CheckExecuted (treat
    // missing data as BREACHING) would alarm permanently (#494/#643/#668).
    // Prod SNS actions gated by retrievalHealthAlarmActionsEnabled GitOps flag,
    // flippable only after a clean promotion + health state (#668/#671). Prod
    // ETL/BM25 operational alarms (above) always keep their actions.
    if (manifestManaged) {
      new RetrievalHealthAlarms(this, 'RetrievalHealthAlarms', {
        alertTopic:
          envName === 'prod' && !props.retrievalHealthAlarmActionsEnabled
            ? undefined
            : alertingTopic?.topic,
        metricNamespace: retrievalMetricNamespace(envName),
      });
    }

    new ssm.StringParameter(this, 'EtlQueueArnParameter', {
      parameterName: `/${envName}/renate/etl-queue-arn`,
      stringValue: this.transformPipeline.processingQueue.queueArn,
      description: 'ETL processing queue ARN for monitoring dashboard',
    });

    new ssm.StringParameter(this, 'EtlDlqArnParameter', {
      parameterName: `/${envName}/renate/etl-dlq-arn`,
      stringValue: this.transformPipeline.dlq.queueArn,
      description: 'ETL DLQ ARN for monitoring dashboard',
    });

    new ssm.StringParameter(this, 'TransformLambdaArnParameter', {
      parameterName: `/${envName}/renate/transform-lambda-arn`,
      stringValue: this.transformPipeline.transformLambda.functionArn,
      description: 'Transform Lambda ARN for monitoring dashboard',
    });

    new ssm.StringParameter(this, 'IngestionBucketNameParameter', {
      parameterName: `/${envName}/renate/ingestion-bucket-name`,
      stringValue: knowledgeBase.ingestionBucket.bucketName,
      description: 'Ingestion bucket name for BM25 index',
    });

    // Avoids cloudformation:DescribeStacks in build-data-artifacts (D7).
    new ssm.StringParameter(this, 'EtlSourceBucketNameParameter', {
      parameterName: `/${envName}/renate/etl-source-bucket-name`,
      stringValue: this.sourceBucket.bucketName,
      description: 'ETL source bucket name for versioned data-artifact uploads',
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseId', {
      value: knowledgeBase.knowledgeBaseId,
      description:
        'The ID of the created Knowledge Base - use this for queries',
      exportName: `${this.stackName}-KnowledgeBaseId`,
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseArn', {
      value: knowledgeBase.knowledgeBaseArn,
      description: 'The ARN of the created Knowledge Base',
      exportName: `${this.stackName}-KnowledgeBaseArn`,
    });

    new cdk.CfnOutput(this, 'IngestionBucketName', {
      value: knowledgeBase.ingestionBucket.bucketName,
      description: 'The name of the S3 bucket for document ingestion',
      exportName: `${this.stackName}-IngestionBucketName`,
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseRoleArn', {
      value: knowledgeBase.knowledgeBaseRole.roleArn,
      description: 'The ARN of the Knowledge Base service role',
      exportName: `${this.stackName}-KnowledgeBaseRoleArn`,
    });

    new cdk.CfnOutput(this, 'VectorBucketName', {
      value: knowledgeBase.vectorBucketName,
      description: 'The name of the S3 Vectors bucket (managed by AWS)',
      exportName: `${this.stackName}-VectorBucketName`,
    });

    new cdk.CfnOutput(this, 'VectorIndexName', {
      value: knowledgeBase.vectorIndexName,
      description: 'The name of the S3 Vectors index',
      exportName: `${this.stackName}-VectorIndexName`,
    });

    new cdk.CfnOutput(this, 'EtlSourceBucketName', {
      value: this.sourceBucket.bucketName,
      description: 'Ingest Bucket for ETL raw data',
      exportName: `${this.stackName}-EtlSourceBucketName`,
    });

    new cdk.CfnOutput(this, 'ProcessingQueueUrl', {
      value: this.transformPipeline.processingQueue.queueUrl,
      description: 'SQS queue URL for ETL processing',
      exportName: `${this.stackName}-ProcessingQueueUrl`,
    });

    new cdk.CfnOutput(this, 'ProcessingQueueArn', {
      value: this.transformPipeline.processingQueue.queueArn,
      description: 'SQS queue ARN for ETL processing',
      exportName: `${this.stackName}-ProcessingQueueArn`,
    });

    new cdk.CfnOutput(this, 'DlqUrl', {
      value: this.transformPipeline.dlq.queueUrl,
      description: 'Dead Letter Queue URL for failed messages',
      exportName: `${this.stackName}-DlqUrl`,
    });

    new cdk.CfnOutput(this, 'TransformLambdaArn', {
      value: this.transformPipeline.transformLambda.functionArn,
      description: 'Transform Lambda function ARN',
      exportName: `${this.stackName}-TransformLambdaArn`,
    });

    new cdk.CfnOutput(this, 'TransformLambdaName', {
      value: this.transformPipeline.transformLambda.functionName,
      description: 'Transform Lambda function name',
      exportName: `${this.stackName}-TransformLambdaName`,
    });
  }
}
