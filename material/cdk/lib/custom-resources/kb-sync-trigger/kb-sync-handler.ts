import {
  BedrockAgentClient,
  StartIngestionJobCommand,
  StartIngestionJobCommandInput,
} from '@aws-sdk/client-bedrock-agent';
import { S3Event, S3EventRecord } from 'aws-lambda';

const bedrock = new BedrockAgentClient({});

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 1000;

interface Environment {
  KNOWLEDGE_BASE_ID: string;
  DATA_SOURCE_ID: string;
}

const env = process.env as unknown as Environment;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startIngestionWithRetry(
  input: StartIngestionJobCommandInput,
): Promise<void> {
  let lastError: Error | undefined;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await bedrock.send(new StartIngestionJobCommand(input));
      console.log(
        `Started ingestion job: ${response.ingestionJob?.ingestionJobId}`,
        `status=${response.ingestionJob?.status}`,
      );
      return;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      const name = (error as any)?.name ?? '';

      // ConflictException: another ingestion job is already running.
      // Re-throw so the caller (SQS event source) retries with backoff.
      // The running job scans the data source at its own start time and may not
      // see changes that arrived after its scan began — a retry ensures those
      // changes are eventually picked up without relying on that assumption.
      if (name === 'ConflictException') {
        console.warn(
          'Ingestion job already in progress — retrying to ensure this change is picked up.',
        );
        throw lastError;
      }

      if (
        name === 'AccessDeniedException' ||
        (error as any)?.code === 'AccessDeniedException' ||
        (typeof (error as any).message === 'string' &&
          (error as any).message.includes('AccessDeniedException'))
      ) {
        console.warn(`AccessDeniedException: ${lastError.message}`);
        throw lastError;
      }
      console.warn(
        `Attempt ${attempt}/${MAX_RETRIES} failed: ${lastError.message}`,
      );

      if (attempt < MAX_RETRIES) {
        const delayMs = BASE_DELAY_MS * 2 ** (attempt - 1); // 1 s, 2 s, 4 s
        console.log(`Retrying in ${delayMs} ms…`);
        await sleep(delayMs);
      }
    }
  }

  // All retries exhausted – throw so Lambda marks the invocation as failed
  // and the CloudWatch alarm on Lambda errors can fire.
  console.error(
    `Failed to start ingestion job after ${MAX_RETRIES} attempts: ${lastError?.message}`,
  );
  throw lastError;
}

/**
 * Lambda handler that triggers Bedrock Knowledge Base ingestion
 * when files are created or deleted in the KB ingestion bucket.
 */
export async function handler(event: S3Event): Promise<void> {
  console.log('Received S3 event:', JSON.stringify(event, null, 2));

  const { KNOWLEDGE_BASE_ID, DATA_SOURCE_ID } = env;

  if (!KNOWLEDGE_BASE_ID || !DATA_SOURCE_ID) {
    throw new Error(
      'KNOWLEDGE_BASE_ID and DATA_SOURCE_ID environment variables are required',
    );
  }

  const relevantRecords = event.Records.filter(
    (record: S3EventRecord) =>
      record.eventName.startsWith('ObjectCreated') ||
      record.eventName.startsWith('ObjectRemoved'),
  );

  if (relevantRecords.length === 0) {
    console.log(
      'No ObjectCreated or ObjectRemoved events found, skipping sync',
    );
    return;
  }

  console.log(`Processing ${relevantRecords.length} S3 event(s)`);

  await startIngestionWithRetry({
    knowledgeBaseId: KNOWLEDGE_BASE_ID,
    dataSourceId: DATA_SOURCE_ID,
    description: `Triggered by S3 event at ${new Date().toISOString()}`,
  });
}
