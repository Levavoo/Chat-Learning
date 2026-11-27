import { Duration } from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';

export const RELEASE_RETENTION_TAG_KEY = 'renate:retention';
export const RELEASE_RETENTION_UNPINNED = 'unpinned';
export const RELEASE_RETENTION_DAYS = 90;

/**
 * Expire only explicitly unpinned immutable release objects.
 *
 * Missing or malformed tags intentionally match no rule. This makes a tagging
 * failure a storage leak instead of a deletion risk.
 */
export function unversionedReleaseRetentionRules(
  idPrefix: string,
  prefixes: string[],
): s3.LifecycleRule[] {
  return prefixes.map((prefix) => ({
    id: `${idPrefix}-${lifecycleIdSuffix(prefix)}-ExpireUnpinned`,
    enabled: true,
    prefix,
    tagFilters: { [RELEASE_RETENTION_TAG_KEY]: RELEASE_RETENTION_UNPINNED },
    expiration: Duration.days(RELEASE_RETENTION_DAYS),
  }));
}

/**
 * Retention for a versioned release bucket.
 *
 * Current versions first receive an S3 delete marker at day 90. Their now
 * noncurrent bytes are removed one day later. Expired delete-marker cleanup
 * must be a separate prefix-only rule because S3 does not allow tag filters on
 * an ExpiredObjectDeleteMarker rule.
 */
export function versionedReleaseRetentionRules(
  idPrefix: string,
  prefixes: string[],
): s3.LifecycleRule[] {
  return prefixes.flatMap((prefix) => [
    {
      id: `${idPrefix}-${lifecycleIdSuffix(prefix)}-ExpireUnpinned`,
      enabled: true,
      prefix,
      tagFilters: { [RELEASE_RETENTION_TAG_KEY]: RELEASE_RETENTION_UNPINNED },
      expiration: Duration.days(RELEASE_RETENTION_DAYS),
      noncurrentVersionExpiration: Duration.days(1),
    },
    {
      id: `${idPrefix}-${lifecycleIdSuffix(prefix)}-DeleteExpiredMarkers`,
      enabled: true,
      prefix,
      expiredObjectDeleteMarker: true,
    },
  ]);
}

function lifecycleIdSuffix(prefix: string): string {
  return prefix
    .replace(/\/$/, '')
    .split('/')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}
