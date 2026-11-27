interface S3ClientType {
  send(command: unknown): Promise<unknown>;
}

interface SsmClientType {
  send(command: unknown): Promise<unknown>;
}

/** A static source entry — prefix is known at deploy time */
interface StaticSourceEntry {
  Type: 'static';
  Prefix: string;
  Suffixes: string[];
}

/** An active-version source entry — version resolved from SSM at runtime */
interface ActiveVersionSourceEntry {
  Type: 'active-version';
  VersionParameterName: string;
  ReleaseBasePrefix: string;
  Suffixes: string[];
}

/** An active-FAQ source entry — FAQ coordinate resolved from SSM at runtime */
interface ActiveFaqSourceEntry {
  Type: 'active-faq';
  VersionParameterName: string;
  ReleaseBasePrefix: string;
  SubPrefix: string;
  Suffixes: string[];
}

type SourceEntry =
  StaticSourceEntry | ActiveVersionSourceEntry | ActiveFaqSourceEntry;

interface ResourceProperties {
  ServiceToken?: string;
  BucketName: string;
  /** Multi-source list replacing the old single Prefix/Suffixes fields */
  Sources?: SourceEntry[];
  ReprocessVersion: string;
  /** Immutable ETL image tag or digest controlling whether a replay is needed. */
  RuntimeIdentity?: string;
}

interface CloudFormationRequest {
  RequestType: 'Create' | 'Update' | 'Delete';
  StackId: string;
  RequestId: string;
  LogicalResourceId: string;
  PhysicalResourceId?: string;
  ResourceProperties: ResourceProperties;
  OldResourceProperties?: ResourceProperties;
}

interface ProviderResponse {
  PhysicalResourceId: string;
  Data?: Record<string, string>;
}

interface ListObjectsOutput {
  Contents?: Array<{ Key?: string }>;
  IsTruncated?: boolean;
  NextContinuationToken?: string;
}

interface HeadObjectOutput {
  Metadata?: Record<string, string>;
  ContentType?: string;
  ContentEncoding?: string;
  ContentLanguage?: string;
  ContentDisposition?: string;
  CacheControl?: string;
  Expires?: Date;
  WebsiteRedirectLocation?: string;
}

interface SsmGetParameterOutput {
  Parameter?: { Value?: string };
}

let s3Client: S3ClientType | null = null;
let ssmClient: SsmClientType | null = null;
let ListObjectsV2CommandClass: new (input: Record<string, unknown>) => unknown;
let HeadObjectCommandClass: new (input: Record<string, unknown>) => unknown;
let CopyObjectCommandClass: new (input: Record<string, unknown>) => unknown;
let GetParameterCommandClass: new (input: Record<string, unknown>) => unknown;

/** Inject mock clients for unit testing. Production code never calls this. */
export function _injectClients(clients: {
  s3?: S3ClientType;
  ssm?: SsmClientType;
  ListObjectsV2Command?: new (input: Record<string, unknown>) => unknown;
  HeadObjectCommand?: new (input: Record<string, unknown>) => unknown;
  CopyObjectCommand?: new (input: Record<string, unknown>) => unknown;
  GetParameterCommand?: new (input: Record<string, unknown>) => unknown;
}): void {
  if (clients.s3 !== undefined) s3Client = clients.s3;
  if (clients.ssm !== undefined) ssmClient = clients.ssm;
  if (clients.ListObjectsV2Command)
    ListObjectsV2CommandClass = clients.ListObjectsV2Command;
  if (clients.HeadObjectCommand)
    HeadObjectCommandClass = clients.HeadObjectCommand;
  if (clients.CopyObjectCommand)
    CopyObjectCommandClass = clients.CopyObjectCommand;
  if (clients.GetParameterCommand)
    GetParameterCommandClass = clients.GetParameterCommand;
}

/** Reset cached clients (for test isolation). */
export function _resetClients(): void {
  s3Client = null;
  ssmClient = null;
}

async function getS3Client(): Promise<S3ClientType> {
  if (!s3Client) {
    // @ts-expect-error - AWS SDK is available in Lambda runtime but excluded from bundle
    const s3Module = await import('@aws-sdk/client-s3');
    const {
      S3Client,
      ListObjectsV2Command,
      HeadObjectCommand,
      CopyObjectCommand,
    } = s3Module;
    s3Client = new S3Client({});
    ListObjectsV2CommandClass = ListObjectsV2Command;
    HeadObjectCommandClass = HeadObjectCommand;
    CopyObjectCommandClass = CopyObjectCommand;
  }
  return s3Client as S3ClientType;
}

async function getSsmClient(): Promise<SsmClientType> {
  if (!ssmClient) {
    // @ts-expect-error - AWS SDK is available in Lambda runtime but excluded from bundle
    const ssmModule = await import('@aws-sdk/client-ssm');
    const { SSMClient, GetParameterCommand } = ssmModule;
    ssmClient = new SSMClient({});
    GetParameterCommandClass = GetParameterCommand;
  }
  return ssmClient as SsmClientType;
}

function objectMatchesSuffix(key: string, suffixes: string[]): boolean {
  return (
    suffixes.length === 0 || suffixes.some((suffix) => key.endsWith(suffix))
  );
}

function encodeCopySource(bucketName: string, key: string): string {
  const encodedKey = key.split('/').map(encodeURIComponent).join('/');
  return `${encodeURIComponent(bucketName)}/${encodedKey}`;
}

function withoutUndefined(
  input: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).filter(([, value]) => value !== undefined),
  );
}

async function listSourceKeys(
  bucketName: string,
  prefix: string,
  suffixes: string[],
): Promise<string[]> {
  const s3 = await getS3Client();
  const keys: string[] = [];
  let continuationToken: string | undefined;

  do {
    const response = (await s3.send(
      new ListObjectsV2CommandClass(
        withoutUndefined({
          Bucket: bucketName,
          Prefix: prefix,
          ContinuationToken: continuationToken,
        }),
      ),
    )) as ListObjectsOutput;

    for (const object of response.Contents ?? []) {
      const key = object.Key;
      if (key && !key.endsWith('/') && objectMatchesSuffix(key, suffixes)) {
        keys.push(key);
      }
    }

    continuationToken = response.NextContinuationToken;
  } while (continuationToken);

  return keys;
}

async function reprocessObject(
  bucketName: string,
  key: string,
  reprocessVersion: string,
): Promise<void> {
  const s3 = await getS3Client();
  const head = (await s3.send(
    new HeadObjectCommandClass({
      Bucket: bucketName,
      Key: key,
    }),
  )) as HeadObjectOutput;

  await s3.send(
    new CopyObjectCommandClass(
      withoutUndefined({
        Bucket: bucketName,
        Key: key,
        CopySource: encodeCopySource(bucketName, key),
        MetadataDirective: 'REPLACE',
        TaggingDirective: 'COPY',
        Metadata: {
          ...(head.Metadata ?? {}),
          'etl-reprocess-version': reprocessVersion,
          'etl-reprocessed-at': new Date().toISOString(),
        },
        ContentType: head.ContentType,
        ContentEncoding: head.ContentEncoding,
        ContentLanguage: head.ContentLanguage,
        ContentDisposition: head.ContentDisposition,
        CacheControl: head.CacheControl,
        Expires: head.Expires,
        WebsiteRedirectLocation: head.WebsiteRedirectLocation,
      }),
    ),
  );
}

async function resolveCoordinatePrefix(
  parameterName: string,
  releaseBasePrefix: string,
  trailingPrefix: string,
  coordinatePattern: RegExp,
  coordinateDescription: string,
  sourceType: 'active-version' | 'active-faq',
): Promise<string | null> {
  const ssm = await getSsmClient();

  let value: string;
  try {
    const resp = (await ssm.send(
      new GetParameterCommandClass({ Name: parameterName }),
    )) as SsmGetParameterOutput;
    value = resp.Parameter?.Value ?? '';
  } catch (err: unknown) {
    const name = (err as { name?: string }).name ?? '';
    if (name === 'ParameterNotFound') {
      console.log(
        `SSM parameter ${parameterName} not found — skipping ${sourceType} source`,
      );
      return null;
    }
    throw err;
  }

  if (!value) {
    console.log(
      `SSM parameter ${parameterName} is empty — skipping ${sourceType} source`,
    );
    return null;
  }

  if (!coordinatePattern.test(value)) {
    throw new Error(
      `SSM parameter ${parameterName} has invalid value "${value}" — expected ${coordinateDescription}`,
    );
  }

  const prefix = `${releaseBasePrefix}${value}/${trailingPrefix}`;
  console.log(`Resolved ${sourceType} prefix: ${prefix}`);
  return prefix;
}

async function resolveActiveVersionPrefix(
  parameterName: string,
  releaseBasePrefix: string,
): Promise<string | null> {
  return resolveCoordinatePrefix(
    parameterName,
    releaseBasePrefix,
    '',
    /^v\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$/,
    'v-prefixed semver (e.g. v1.5.0)',
    'active-version',
  );
}

async function resolveActiveFaqPrefix(
  parameterName: string,
  releaseBasePrefix: string,
  subPrefix: string,
): Promise<string | null> {
  return resolveCoordinatePrefix(
    parameterName,
    releaseBasePrefix,
    subPrefix,
    /^sha256-[0-9a-f]{64}$/,
    'sha256- followed by 64 lowercase hexadecimal characters',
    'active-faq',
  );
}

export async function handler(
  event: CloudFormationRequest,
): Promise<ProviderResponse> {
  console.log('Received event:', JSON.stringify(event, null, 2));

  const props = event.ResourceProperties;
  const bucketName = props.BucketName;
  const reprocessVersion = props.ReprocessVersion;
  const physicalResourceId =
    event.PhysicalResourceId || `source-reprocess-${bucketName}`;

  if (event.RequestType === 'Delete') {
    console.log('Delete request - no source object reprocessing needed');
    return { PhysicalResourceId: physicalResourceId };
  }

  // The deployment-controlled environment flag is authoritative so a crafted
  // direct invocation cannot re-enable source writes through event props.
  if (process.env.SOURCE_REPROCESS_ENABLED === 'false') {
    console.log('Source reprocess is disabled for this environment');
    return {
      PhysicalResourceId: physicalResourceId,
      Data: {
        Reprocessed: '0',
        ReprocessVersion: reprocessVersion,
        SkipReason: 'environment-disabled',
      },
    };
  }

  if (event.RequestType === 'Update' && props.RuntimeIdentity) {
    const oldProps = event.OldResourceProperties;
    const sourceConfigurationUnchanged =
      oldProps?.BucketName === props.BucketName &&
      JSON.stringify(oldProps?.Sources ?? []) ===
        JSON.stringify(props.Sources ?? []);

    if (sourceConfigurationUnchanged) {
      const oldRuntimeIdentity = oldProps?.RuntimeIdentity;
      if (!oldRuntimeIdentity || oldRuntimeIdentity === props.RuntimeIdentity) {
        const skipReason = oldRuntimeIdentity
          ? 'runtime-identity-unchanged'
          : 'runtime-identity-migration';
        console.log(
          `Skipping source reprocess: ${skipReason} (${props.RuntimeIdentity})`,
        );
        return {
          PhysicalResourceId: physicalResourceId,
          Data: {
            Reprocessed: '0',
            ReprocessVersion: reprocessVersion,
            RuntimeIdentity: props.RuntimeIdentity,
            SkipReason: skipReason,
          },
        };
      }
    }
  }

  const sources = props.Sources ?? [];
  if (sources.length === 0) {
    console.log('No sources configured — nothing to reprocess');
    return {
      PhysicalResourceId: physicalResourceId,
      Data: { Reprocessed: '0' },
    };
  }

  let totalReprocessed = 0;

  for (const source of sources) {
    if (source.Type === 'static') {
      const keys = await listSourceKeys(
        bucketName,
        source.Prefix,
        source.Suffixes,
      );
      console.log(
        `Static source ${source.Prefix}: reprocessing ${keys.length} objects`,
      );
      for (const [index, key] of keys.entries()) {
        console.log(`  [${index + 1}/${keys.length}] ${key}`);
        await reprocessObject(bucketName, key, reprocessVersion);
      }
      totalReprocessed += keys.length;
    } else if (source.Type === 'active-version') {
      const prefix = await resolveActiveVersionPrefix(
        source.VersionParameterName,
        source.ReleaseBasePrefix,
      );
      if (prefix === null) {
        // Fresh environment or missing pointer — skip gracefully
        continue;
      }
      const keys = await listSourceKeys(bucketName, prefix, source.Suffixes);
      console.log(
        `Active-version source ${prefix}: reprocessing ${keys.length} objects`,
      );
      for (const [index, key] of keys.entries()) {
        console.log(`  [${index + 1}/${keys.length}] ${key}`);
        await reprocessObject(bucketName, key, reprocessVersion);
      }
      totalReprocessed += keys.length;
    } else if (source.Type === 'active-faq') {
      const prefix = await resolveActiveFaqPrefix(
        source.VersionParameterName,
        source.ReleaseBasePrefix,
        source.SubPrefix,
      );
      if (prefix === null) {
        // Fresh environment or missing FAQ pointer — skip gracefully
        continue;
      }
      const keys = await listSourceKeys(bucketName, prefix, source.Suffixes);
      console.log(
        `Active-faq source ${prefix}: reprocessing ${keys.length} objects`,
      );
      for (const [index, key] of keys.entries()) {
        console.log(`  [${index + 1}/${keys.length}] ${key}`);
        await reprocessObject(bucketName, key, reprocessVersion);
      }
      totalReprocessed += keys.length;
    } else {
      // Unknown source type — fail loudly rather than silently skipping.
      // A malformed Sources property is a deploy-time error, not a no-op.
      throw new Error(
        `Unknown source Type: ${JSON.stringify((source as { Type?: string }).Type)} — expected "static", "active-version", or "active-faq"`,
      );
    }
  }

  return {
    PhysicalResourceId: physicalResourceId,
    Data: {
      BucketName: bucketName,
      Reprocessed: String(totalReprocessed),
      ReprocessVersion: reprocessVersion,
      ...(props.RuntimeIdentity && {
        RuntimeIdentity: props.RuntimeIdentity,
      }),
    },
  };
}
