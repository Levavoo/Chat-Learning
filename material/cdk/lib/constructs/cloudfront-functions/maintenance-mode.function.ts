import cf from 'cloudfront';

const MAINTENANCE_KEY = 'maintenance';
const MAINTENANCE_PAGE_URI = '/_maintenance/index.html';
const MAINTENANCE_PREFIX = '/_maintenance/';
const BYPASS_TOKEN = 'r3d4kt10n';

/** True for SPA routes and root path; false for static assets or the maintenance page. */
function isApplicationPageRequest(uri: string): boolean {
  if (uri.indexOf(MAINTENANCE_PREFIX) === 0) {
    return false;
  }
  const lastSegment = uri.substring(uri.lastIndexOf('/') + 1);
  return lastSegment.indexOf('.') === -1;
}

/**
 * Angular uses HashLocationStrategy, so client routes live behind `#` and are
 * invisible to CloudFront. Dashboard bypass therefore uses `?bypass=…` instead
 * of a path check; real auth is Cognito + DashboardGuard.
 */
async function handler(event: any): Promise<any> {
  const request = event.request;

  if (!isApplicationPageRequest(request.uri)) {
    return request;
  }

  // Only skips the maintenance page — not an auth replacement.
  const bypassParam = request.querystring?.bypass?.value;
  if (bypassParam === BYPASS_TOKEN) {
    request.uri = '/index.html';
    return request;
  }

  const kvsHandle = cf.kvs();
  let maintenance = 'off';
  try {
    maintenance = await kvsHandle.get(MAINTENANCE_KEY);
  } catch {
    // Key may not have propagated to this edge yet.
    maintenance = 'off';
  }

  if (maintenance === 'on') {
    request.uri = MAINTENANCE_PAGE_URI;
  } else {
    // SPA routing: rewrite to /index.html. Distribution-level errorResponses
    // would otherwise swallow API 403/404 from the API GW behaviors.
    request.uri = '/index.html';
  }

  return request;
}

export { handler };
