import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, resolve, sep } from 'node:path';

const HOST = '127.0.0.1';
const PORT = Number.parseInt(process.env.SMOKE_PORT ?? '4173', 10);
const DIST_ROOT = resolve(
  process.cwd(),
  process.env.SMOKE_DIST_DIR ?? 'dist/ng-digibro-frontend/browser',
);
const ARTIFACT_HEADER = 'production-dist';

const contentTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webp', 'image/webp'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
]);

try {
  const dist = await stat(DIST_ROOT);
  if (!dist.isDirectory()) {
    throw new Error('path is not a directory');
  }
} catch (error) {
  const detail = error instanceof Error ? error.message : String(error);
  console.error(
    `frontend smoke static server: missing dist at ${DIST_ROOT}: ${detail}`,
  );
  process.exit(1);
}

const server = createServer(async (request, response) => {
  response.setHeader('X-Frontend-Smoke-Artifact', ARTIFACT_HEADER);
  response.setHeader('Cache-Control', 'no-store');

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, { Allow: 'GET, HEAD' });
    response.end('Method not allowed');
    return;
  }

  let pathname;
  try {
    pathname = decodeURIComponent(
      new URL(request.url ?? '/', `http://${HOST}`).pathname,
    );
  } catch {
    response.writeHead(400);
    response.end('Bad request');
    return;
  }

  const relativePath =
    pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
  const filePath = resolve(DIST_ROOT, relativePath);
  if (filePath !== DIST_ROOT && !filePath.startsWith(`${DIST_ROOT}${sep}`)) {
    response.writeHead(403);
    response.end('Forbidden');
    return;
  }

  try {
    const file = await stat(filePath);
    if (!file.isFile()) {
      throw new Error('not a file');
    }

    response.writeHead(200, {
      'Content-Length': file.size,
      'Content-Type':
        contentTypes.get(extname(filePath).toLowerCase()) ??
        'application/octet-stream',
    });
    if (request.method === 'HEAD') {
      response.end();
      return;
    }
    createReadStream(filePath).pipe(response);
  } catch {
    response.writeHead(404);
    response.end('Not found');
  }
});

server.on('error', (error) => {
  console.error(`frontend smoke static server: ${error.message}`);
  process.exitCode = 1;
});

server.listen(PORT, HOST, () => {
  console.log(
    `Serving production frontend artifact from ${DIST_ROOT} at http://${HOST}:${PORT}`,
  );
});

const shutdown = () => server.close(() => process.exit(0));
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
