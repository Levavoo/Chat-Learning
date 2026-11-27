import {
  handler,
  _injectClients,
  _resetClients,
} from '../../lib/custom-resources/source-reprocess/source-reprocess-handler';

const mockSend = jest.fn();

function makeMockClient() {
  return { send: mockSend };
}

/** A pass-through command constructor that records its input as properties. */
function makeCommand(type: string) {
  return jest.fn().mockImplementation((input: Record<string, unknown>) => ({
    _type: type,
    ...input,
  }));
}

beforeEach(() => {
  jest.clearAllMocks();
  delete process.env.SOURCE_REPROCESS_ENABLED;
  _resetClients();
  _injectClients({
    s3: makeMockClient(),
    ssm: makeMockClient(),
    ListObjectsV2Command: makeCommand('ListObjectsV2'),
    HeadObjectCommand: makeCommand('HeadObject'),
    CopyObjectCommand: makeCommand('CopyObject'),
    GetParameterCommand: makeCommand('GetParameter'),
  });
});

afterEach(() => {
  delete process.env.SOURCE_REPROCESS_ENABLED;
});

function makeEvent(overrides: Record<string, unknown> = {}): any {
  return {
    RequestType: 'Create',
    StackId: 'arn:aws:cloudformation:eu-central-1:123:stack/test/abc',
    RequestId: 'req-1',
    LogicalResourceId: 'SourceReprocessTrigger',
    ResourceProperties: {
      BucketName: 'test-bucket',
      Sources: [],
      ReprocessVersion: 'v-test',
    },
    ...overrides,
  };
}

describe('Delete no-op', () => {
  test('Delete request returns PhysicalResourceId without calling S3 or SSM', async () => {
    const event = makeEvent({
      RequestType: 'Delete',
      PhysicalResourceId: 'existing-id',
    });
    const result = await handler(event);
    expect(result.PhysicalResourceId).toBe('existing-id');
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('Environment disable gate', () => {
  test('returns a stable no-op before any source access', async () => {
    process.env.SOURCE_REPROCESS_ENABLED = 'false';
    const result = await handler(
      makeEvent({
        PhysicalResourceId: 'retained-preprod-id',
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [
            {
              Type: 'static',
              Prefix: 'IN/faq/',
              Suffixes: ['.html'],
            },
          ],
          ReprocessVersion: 'v-disabled',
        },
      }),
    );

    expect(result).toEqual({
      PhysicalResourceId: 'retained-preprod-id',
      Data: {
        Reprocessed: '0',
        ReprocessVersion: 'v-disabled',
        SkipReason: 'environment-disabled',
      },
    });
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('Runtime identity update gate', () => {
  const source = {
    Type: 'static' as const,
    Prefix: 'IN/faq/',
    Suffixes: ['.html'],
  };

  test('first runtime-identity deployment is a migration-safe no-op', async () => {
    const result = await handler(
      makeEvent({
        RequestType: 'Update',
        PhysicalResourceId: 'existing-id',
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'new-source-hash',
          RuntimeIdentity: 'v1.83.3-qa-blue-baseline',
        },
        OldResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'old-source-hash',
        },
      }),
    );

    expect(result).toEqual(
      expect.objectContaining({
        PhysicalResourceId: 'existing-id',
        Data: expect.objectContaining({
          Reprocessed: '0',
          SkipReason: 'runtime-identity-migration',
        }),
      }),
    );
    expect(mockSend).not.toHaveBeenCalled();
  });

  test('source fingerprint changes do not replay an unchanged ETL image', async () => {
    const result = await handler(
      makeEvent({
        RequestType: 'Update',
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'new-source-hash',
          RuntimeIdentity: 'v1.108.3',
        },
        OldResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'old-source-hash',
          RuntimeIdentity: 'v1.108.3',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('0');
    expect(result.Data?.SkipReason).toBe('runtime-identity-unchanged');
    expect(mockSend).not.toHaveBeenCalled();
  });

  test('source configuration changes still replay an unchanged ETL image', async () => {
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/drv.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({ Metadata: {}, ContentType: 'text/html' })
      .mockResolvedValueOnce({});

    const result = await handler(
      makeEvent({
        RequestType: 'Update',
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'same-source-hash',
          RuntimeIdentity: 'v1.108.3',
        },
        OldResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [],
          ReprocessVersion: 'same-source-hash',
          RuntimeIdentity: 'v1.108.3',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('1');
    expect(mockSend).toHaveBeenCalledTimes(3);
  });

  test('a new ETL image still reprocesses the configured sources', async () => {
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/drv.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({ Metadata: {}, ContentType: 'text/html' })
      .mockResolvedValueOnce({});

    const result = await handler(
      makeEvent({
        RequestType: 'Update',
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'new-source-hash',
          RuntimeIdentity: 'v1.109.0',
        },
        OldResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'old-source-hash',
          RuntimeIdentity: 'v1.108.3',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('1');
    expect(mockSend).toHaveBeenCalledTimes(3);
  });
});

describe('Empty sources list', () => {
  test('returns Reprocessed=0 without calling S3', async () => {
    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [],
        ReprocessVersion: 'v1',
      },
    });
    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('0');
    expect(mockSend).not.toHaveBeenCalled();
  });
});

describe('Static source entry', () => {
  test('lists and reprocesses objects matching suffix filter only', async () => {
    mockSend
      .mockResolvedValueOnce({
        Contents: [
          { Key: 'IN/faq/drv.html' },
          { Key: 'IN/faq/drv.xml' }, // filtered out — .xml not in suffixes
        ],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({ Metadata: {}, ContentType: 'text/html' })
      .mockResolvedValueOnce({});

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [{ Type: 'static', Prefix: 'IN/faq/', Suffixes: ['.html'] }],
        ReprocessVersion: 'v1',
      },
    });

    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('1');
    expect(mockSend).toHaveBeenCalledTimes(3);
  });

  test('handles paginated S3 listing', async () => {
    mockSend
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/a.html' }],
        IsTruncated: true,
        NextContinuationToken: 'tok',
      })
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/b.html' }],
        IsTruncated: false,
      })
      .mockResolvedValue({});

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [{ Type: 'static', Prefix: 'IN/faq/', Suffixes: ['.html'] }],
        ReprocessVersion: 'v1',
      },
    });

    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('2');
  });
});

describe('Active-version source — valid SSM pointer', () => {
  test('resolves version from SSM and constructs releases/<version>/ prefix', async () => {
    mockSend
      .mockResolvedValueOnce({ Parameter: { Value: 'v1.5.0' } })
      .mockResolvedValueOnce({
        Contents: [
          { Key: 'releases/v1.5.0/xml/B01.xml' },
          { Key: 'releases/v1.5.0/pdf/V0090.pdf' },
          { Key: 'releases/v1.5.0/xml/B01.html' },
        ],
        IsTruncated: false,
      })
      .mockResolvedValue({});

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml', '.pdf'],
          },
        ],
        ReprocessVersion: 'etl-hash',
      },
    });

    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('2');

    // Second call is ListObjectsV2 — verify Prefix
    const listCall = mockSend.mock.calls[1][0];
    expect(listCall.Prefix).toBe('releases/v1.5.0/');
  });

  test('GetParameter is called with the correct parameter name', async () => {
    mockSend
      .mockResolvedValueOnce({ Parameter: { Value: 'v2.3.1' } })
      .mockResolvedValueOnce({ Contents: [], IsTruncated: false });

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml'],
          },
        ],
        ReprocessVersion: 'hash',
      },
    });

    await handler(event);
    const getParamCall = mockSend.mock.calls[0][0];
    expect(getParamCall.Name).toBe('/dev/renate/data-artifact-version');
  });
});

describe('Active-version source — ParameterNotFound (fresh environment)', () => {
  test('logs skip and returns Reprocessed=0 without throwing', async () => {
    mockSend.mockRejectedValueOnce(
      Object.assign(new Error('Parameter not found'), {
        name: 'ParameterNotFound',
      }),
    );

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml', '.pdf'],
          },
        ],
        ReprocessVersion: 'hash',
      },
    });

    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('0');
    expect(mockSend).toHaveBeenCalledTimes(1); // only GetParameter
  });
});

describe('Active-version source — empty SSM value', () => {
  test('skips gracefully when parameter value is empty string', async () => {
    mockSend.mockResolvedValueOnce({ Parameter: { Value: '' } });

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml'],
          },
        ],
        ReprocessVersion: 'hash',
      },
    });

    const result = await handler(event);
    expect(result.Data?.Reprocessed).toBe('0');
    expect(mockSend).toHaveBeenCalledTimes(1);
  });
});

describe('Active-version source — invalid version format', () => {
  test('throws when SSM value is missing v-prefix', async () => {
    mockSend.mockResolvedValueOnce({ Parameter: { Value: '1.5.0' } });

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml'],
          },
        ],
        ReprocessVersion: 'hash',
      },
    });

    await expect(handler(event)).rejects.toThrow(/invalid value "1\.5\.0"/);
  });

  test('throws when SSM value is a random string', async () => {
    mockSend.mockResolvedValueOnce({ Parameter: { Value: 'latest' } });

    await expect(
      handler(
        makeEvent({
          ResourceProperties: {
            BucketName: 'test-bucket',
            Sources: [
              {
                Type: 'active-version',
                VersionParameterName: '/dev/renate/data-artifact-version',
                ReleaseBasePrefix: 'releases/',
                Suffixes: ['.xml'],
              },
            ],
            ReprocessVersion: 'hash',
          },
        }),
      ),
    ).rejects.toThrow(/invalid value/);
  });

  test.each(['v1.2.3.4', 'v1.2.3/x', 'v1.2.3 ', 'v1.2.3-'])(
    'throws for non-anchored / malformed value %p',
    async (badValue) => {
      mockSend.mockResolvedValueOnce({ Parameter: { Value: badValue } });

      await expect(
        handler(
          makeEvent({
            ResourceProperties: {
              BucketName: 'test-bucket',
              Sources: [
                {
                  Type: 'active-version',
                  VersionParameterName: '/dev/renate/data-artifact-version',
                  ReleaseBasePrefix: 'releases/',
                  Suffixes: ['.xml'],
                },
              ],
              ReprocessVersion: 'hash',
            },
          }),
        ),
      ).rejects.toThrow(/invalid value/);
    },
  );

  test.each(['v1.5.0', 'v1.5.0-rc.1', 'v2.0.0+build.7'])(
    'accepts valid semver %p',
    async (goodValue) => {
      mockSend
        .mockResolvedValueOnce({ Parameter: { Value: goodValue } })
        .mockResolvedValueOnce({ Contents: [], IsTruncated: false });

      const result = await handler(
        makeEvent({
          ResourceProperties: {
            BucketName: 'test-bucket',
            Sources: [
              {
                Type: 'active-version',
                VersionParameterName: '/dev/renate/data-artifact-version',
                ReleaseBasePrefix: 'releases/',
                Suffixes: ['.xml'],
              },
            ],
            ReprocessVersion: 'hash',
          },
        }),
      );
      // Valid version → listing runs (empty here) → Reprocessed=0, no throw
      expect(result.Data?.Reprocessed).toBe('0');
      const listCall = mockSend.mock.calls[1][0];
      expect(listCall.Prefix).toBe(`releases/${goodValue}/`);
    },
  );
});

describe('Active-version source — non-ParameterNotFound SSM error propagates', () => {
  test('AccessDeniedException is re-thrown without swallowing', async () => {
    mockSend.mockRejectedValueOnce(
      Object.assign(new Error('Access denied'), {
        name: 'AccessDeniedException',
      }),
    );

    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [
          {
            Type: 'active-version',
            VersionParameterName: '/dev/renate/data-artifact-version',
            ReleaseBasePrefix: 'releases/',
            Suffixes: ['.xml'],
          },
        ],
        ReprocessVersion: 'hash',
      },
    });

    await expect(handler(event)).rejects.toThrow('Access denied');
  });
});

describe('Unknown source Type', () => {
  test('throws instead of silently skipping an unknown Type', async () => {
    const event = makeEvent({
      ResourceProperties: {
        BucketName: 'test-bucket',
        Sources: [{ Type: 'bogus', Prefix: 'x/', Suffixes: ['.xml'] } as any],
        ReprocessVersion: 'v1',
      },
    });

    await expect(handler(event)).rejects.toThrow(/Unknown source Type/);
  });
});

describe('Active FAQ source', () => {
  const hash = 'a'.repeat(64);
  const source = {
    Type: 'active-faq',
    VersionParameterName: '/dev/renate/faq-artifact-version',
    ReleaseBasePrefix: 'releases/faq/',
    SubPrefix: 'html/',
    Suffixes: ['.html'],
  };

  test('valid pointer lists and reprocesses only the active FAQ HTML prefix', async () => {
    mockSend
      .mockResolvedValueOnce({ Parameter: { Value: `sha256-${hash}` } })
      .mockResolvedValueOnce({
        Contents: [
          {
            Key: `releases/faq/sha256-${hash}/html/faq-a-und-b.html`,
          },
          { Key: `releases/faq/sha256-${hash}/html/ignored.json` },
        ],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({ Metadata: {}, ContentType: 'text/html' })
      .mockResolvedValueOnce({});

    const result = await handler(
      makeEvent({
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'faq-test',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('1');
    expect(mockSend.mock.calls[1][0]).toEqual(
      expect.objectContaining({
        _type: 'ListObjectsV2',
        Prefix: `releases/faq/sha256-${hash}/html/`,
      }),
    );
  });

  test('missing or empty pointer is a successful no-op', async () => {
    mockSend.mockRejectedValueOnce(
      Object.assign(new Error('missing'), { name: 'ParameterNotFound' }),
    );
    const missing = await handler(
      makeEvent({
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'faq-test',
        },
      }),
    );
    expect(missing.Data?.Reprocessed).toBe('0');

    mockSend.mockResolvedValueOnce({ Parameter: { Value: '' } });
    const empty = await handler(
      makeEvent({
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [source],
          ReprocessVersion: 'faq-test',
        },
      }),
    );
    expect(empty.Data?.Reprocessed).toBe('0');
  });

  test.each([
    'sha256-short',
    `sha256-${'A'.repeat(64)}`,
    `sha256-${'a'.repeat(64)}/html`,
    `v1.2.3`,
  ])('rejects malformed coordinate %s', async (coordinate) => {
    mockSend.mockResolvedValueOnce({ Parameter: { Value: coordinate } });
    await expect(
      handler(
        makeEvent({
          ResourceProperties: {
            BucketName: 'test-bucket',
            Sources: [source],
            ReprocessVersion: 'faq-test',
          },
        }),
      ),
    ).rejects.toThrow(/64 lowercase hexadecimal/);
  });

  test('non-ParameterNotFound SSM error propagates', async () => {
    mockSend.mockRejectedValueOnce(
      Object.assign(new Error('denied'), { name: 'AccessDeniedException' }),
    );
    await expect(
      handler(
        makeEvent({
          ResourceProperties: {
            BucketName: 'test-bucket',
            Sources: [source],
            ReprocessVersion: 'faq-test',
          },
        }),
      ),
    ).rejects.toThrow('denied');
  });
});

describe('Mixed sources (active-version + static)', () => {
  test('processes both entries and sums Reprocessed count', async () => {
    mockSend
      .mockResolvedValueOnce({ Parameter: { Value: 'v1.0.0' } })
      .mockResolvedValueOnce({
        Contents: [{ Key: 'releases/v1.0.0/xml/B01.xml' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/drv.html' }],
        IsTruncated: false,
      })
      .mockResolvedValueOnce({})
      .mockResolvedValueOnce({});

    const result = await handler(
      makeEvent({
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [
            {
              Type: 'active-version',
              VersionParameterName: '/dev/renate/data-artifact-version',
              ReleaseBasePrefix: 'releases/',
              Suffixes: ['.xml', '.pdf'],
            },
            { Type: 'static', Prefix: 'IN/faq/', Suffixes: ['.html'] },
          ],
          ReprocessVersion: 'mixed',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('2');
  });

  test('ParameterNotFound on active-version still processes static source', async () => {
    mockSend
      .mockRejectedValueOnce(
        Object.assign(new Error('not found'), { name: 'ParameterNotFound' }),
      )
      .mockResolvedValueOnce({
        Contents: [{ Key: 'IN/faq/drv.html' }],
        IsTruncated: false,
      })
      .mockResolvedValue({});

    const result = await handler(
      makeEvent({
        ResourceProperties: {
          BucketName: 'test-bucket',
          Sources: [
            {
              Type: 'active-version',
              VersionParameterName: '/dev/renate/data-artifact-version',
              ReleaseBasePrefix: 'releases/',
              Suffixes: ['.xml'],
            },
            { Type: 'static', Prefix: 'IN/faq/', Suffixes: ['.html'] },
          ],
          ReprocessVersion: 'hash',
        },
      }),
    );

    expect(result.Data?.Reprocessed).toBe('1');
  });
});
