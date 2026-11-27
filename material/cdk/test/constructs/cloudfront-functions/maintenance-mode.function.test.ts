jest.mock(
  'cloudfront',
  () => ({
    __esModule: true,
    default: { kvs: jest.fn() },
  }),
  { virtual: true },
);

import cf from 'cloudfront';
import { handler } from '../../../lib/constructs/cloudfront-functions/maintenance-mode.function';

function makeEvent(
  uri: string,
  querystring?: Record<string, { value: string }>,
) {
  return { request: { uri, querystring: querystring ?? {} } };
}

describe('maintenance-mode handler', () => {
  const kvsGet = jest.fn();

  beforeEach(() => {
    kvsGet.mockReset();
    (cf.kvs as jest.Mock).mockReturnValue({ get: kvsGet });
  });

  test('passes through static asset requests without consulting the KVS', async () => {
    const event = makeEvent('/assets/logo.svg');

    const result = await handler(event);

    expect(result).toBe(event.request);
    expect(kvsGet).not.toHaveBeenCalled();
  });

  test('rewrites application page requests to /index.html when maintenance is off (SPA routing)', async () => {
    kvsGet.mockResolvedValue('off');
    const event = makeEvent('/chat');

    const result = await handler(event);

    expect(result.uri).toBe('/index.html');
  });

  test('rewrites application page requests to the maintenance page when maintenance is on', async () => {
    kvsGet.mockResolvedValue('on');
    const event = makeEvent('/chat');

    const result = await handler(event);

    expect(result.uri).toBe('/_maintenance/index.html');
  });

  test('falls back to SPA routing when the KVS key is not found', async () => {
    kvsGet.mockRejectedValue(new Error('Key not found'));
    const event = makeEvent('/chat');

    const result = await handler(event);

    expect(result.uri).toBe('/index.html');
  });

  test('bypass query param serves SPA during maintenance mode', async () => {
    // KVS is never consulted — the bypass fires before the async KVS call.
    kvsGet.mockResolvedValue('on');
    const event = makeEvent('/', { bypass: { value: 'r3d4kt10n' } });

    const result = await handler(event);

    expect(result.uri).toBe('/index.html');
    expect(kvsGet).not.toHaveBeenCalled();
  });

  test('bypass query param also works when maintenance is off (normal SPA routing)', async () => {
    kvsGet.mockResolvedValue('off');
    const event = makeEvent('/', { bypass: { value: 'r3d4kt10n' } });

    const result = await handler(event);

    expect(result.uri).toBe('/index.html');
    expect(kvsGet).not.toHaveBeenCalled();
  });

  test('wrong bypass token still shows maintenance page', async () => {
    kvsGet.mockResolvedValue('on');
    const event = makeEvent('/', { bypass: { value: 'wrong-token' } });

    const result = await handler(event);

    expect(result.uri).toBe('/_maintenance/index.html');
  });

  test('normal user routes still show maintenance page when maintenance is on', async () => {
    kvsGet.mockResolvedValue('on');
    const event = makeEvent('/chat');

    const result = await handler(event);

    expect(result.uri).toBe('/_maintenance/index.html');
  });
});
