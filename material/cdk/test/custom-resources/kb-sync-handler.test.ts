import { handler } from '../../lib/custom-resources/kb-sync-trigger/kb-sync-handler';
import { S3Event, S3EventRecord } from 'aws-lambda';
import {
  BedrockAgentClient,
  StartIngestionJobCommand,
} from '@aws-sdk/client-bedrock-agent';
import { mockClient } from 'aws-sdk-client-mock';

const bedrockMock = mockClient(BedrockAgentClient);

const createS3Event = (
  key: string,
  eventName: string = 'ObjectCreated:Put',
): S3Event => ({
  Records: [
    {
      eventVersion: '2.1',
      eventSource: 'aws:s3',
      awsRegion: 'eu-central-1',
      eventTime: new Date().toISOString(),
      eventName,
      userIdentity: { principalId: 'test' },
      requestParameters: { sourceIPAddress: '127.0.0.1' },
      responseElements: {
        'x-amz-request-id': 'test',
        'x-amz-id-2': 'test',
      },
      s3: {
        s3SchemaVersion: '1.0',
        configurationId: 'test',
        bucket: {
          name: 'test-bucket',
          ownerIdentity: { principalId: 'test' },
          arn: 'arn:aws:s3:::test-bucket',
        },
        object: {
          key,
          size: 1000,
          eTag: 'test',
          sequencer: 'test',
        },
      },
    } as S3EventRecord,
  ],
});

describe('KB Sync Handler', () => {
  beforeEach(() => {
    bedrockMock.reset();
    process.env.KNOWLEDGE_BASE_ID = 'test-kb-id';
    process.env.DATA_SOURCE_ID = 'test-ds-id';
  });

  describe('ObjectCreated events', () => {
    test('starts ingestion job on ObjectCreated:Put', async () => {
      bedrockMock.on(StartIngestionJobCommand).resolves({
        ingestionJob: {
          ingestionJobId: 'job-123',
          status: 'STARTING',
          knowledgeBaseId: 'test-kb-id',
          dataSourceId: 'test-ds-id',
          startedAt: new Date(),
          updatedAt: new Date(),
        },
      });

      await handler(createS3Event('docs/test.md.metadata.json'));

      expect(bedrockMock.calls()).toHaveLength(1);
    });
  });

  describe('ObjectRemoved events', () => {
    test('starts ingestion job on ObjectRemoved:Delete', async () => {
      bedrockMock.on(StartIngestionJobCommand).resolves({
        ingestionJob: {
          ingestionJobId: 'job-456',
          status: 'STARTING',
          knowledgeBaseId: 'test-kb-id',
          dataSourceId: 'test-ds-id',
          startedAt: new Date(),
          updatedAt: new Date(),
        },
      });

      await handler(
        createS3Event(
          'docs/B01/B01_0000.md.metadata.json',
          'ObjectRemoved:Delete',
        ),
      );

      expect(bedrockMock.calls()).toHaveLength(1);
    });

    test('skips sync for unrelated event types', async () => {
      await handler(
        createS3Event('docs/test.md.metadata.json', 'ObjectRestore:Completed'),
      );
      expect(bedrockMock.calls()).toHaveLength(0);
    });
  });

  describe('ConflictException handling', () => {
    test('re-throws ConflictException so SQS retries the invocation', async () => {
      bedrockMock.on(StartIngestionJobCommand).rejects({
        name: 'ConflictException',
        message: 'Knowledge Base already in use',
        $metadata: { httpStatusCode: 409 },
      });

      // Should throw — SQS will retry the invocation with backoff,
      // ensuring changes that arrived after the running job's scan are picked up.
      await expect(
        handler(createS3Event('docs/test.md.metadata.json')),
      ).rejects.toThrow('Knowledge Base already in use');

      // Only called once — no internal retry for ConflictException
      expect(bedrockMock.calls()).toHaveLength(1);
    });
  });

  describe('ThrottlingException retry', () => {
    test('retries on ThrottlingException with backoff', async () => {
      bedrockMock
        .on(StartIngestionJobCommand)
        .rejectsOnce({
          name: 'ThrottlingException',
          message: 'Rate limit exceeded',
          $metadata: { httpStatusCode: 429 },
        })
        .resolves({
          ingestionJob: {
            ingestionJobId: 'job-123',
            status: 'STARTING',
            knowledgeBaseId: 'test-kb-id',
            dataSourceId: 'test-ds-id',
            startedAt: new Date(),
            updatedAt: new Date(),
          },
        });

      await handler(createS3Event('docs/test.md.metadata.json'));

      expect(bedrockMock.calls()).toHaveLength(2);
    });
  });

  describe('AccessDeniedException', () => {
    test('throws immediately on AccessDeniedException without retry', async () => {
      bedrockMock.on(StartIngestionJobCommand).rejects({
        name: 'AccessDeniedException',
        message: 'Not authorized',
        $metadata: { httpStatusCode: 403 },
      });

      await expect(
        handler(createS3Event('docs/test.md.metadata.json')),
      ).rejects.toThrow('Not authorized');

      expect(bedrockMock.calls()).toHaveLength(1);
    });
  });

  describe('max retries exhausted', () => {
    test('throws after 3 failed attempts for non-conflict errors', async () => {
      bedrockMock.on(StartIngestionJobCommand).rejects({
        name: 'ServiceUnavailableException',
        message: 'Service unavailable',
        $metadata: { httpStatusCode: 503 },
      });

      await expect(
        handler(createS3Event('docs/test.md.metadata.json')),
      ).rejects.toThrow();

      expect(bedrockMock.calls()).toHaveLength(3);
    });
  });
});
