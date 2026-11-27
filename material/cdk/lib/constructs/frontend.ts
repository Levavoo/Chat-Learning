import { Construct } from 'constructs';
import { join } from 'path';
import { CfnOutput, Duration, RemovalPolicy, Stack } from 'aws-cdk-lib';
import {
  BlockPublicAccess,
  Bucket,
  BucketEncryption,
  IBucket,
} from 'aws-cdk-lib/aws-s3';
import {
  AllowedMethods,
  CachePolicy,
  Distribution,
  FunctionCode,
  FunctionEventType,
  FunctionRuntime,
  Function as CloudFrontFunction,
  GeoRestriction,
  HeadersFrameOption,
  HeadersReferrerPolicy,
  ImportSource,
  KeyValueStore,
  OriginRequestPolicy,
  ResponseHeadersPolicy,
  SecurityPolicyProtocol,
  ViewerProtocolPolicy,
} from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin, S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import { bundleCloudFrontFunctionCode } from './cloudfront-functions/bundle';
import { NagSuppressions } from 'cdk-nag';
import * as route53 from 'aws-cdk-lib/aws-route53';
import * as targets from 'aws-cdk-lib/aws-route53-targets';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';

export interface FrontendProps {
  readonly prefix: string;
  readonly envName: string;
  readonly webAclId?: string;
  readonly accessLogBucket?: IBucket;
  readonly enableIpV6: boolean;
  /** CloudFront alias (e.g. chat.example.com). */
  readonly alternateDomainName?: string;
  /** Required with alternateDomainName. */
  readonly hostedZoneId?: string;
  /** Required for ccTLDs or when auto-extraction from alternateDomainName would be wrong. */
  readonly hostedZoneName?: string;
  /** Pre-existing cert ARN (must be us-east-1); skips DNS validation path. */
  readonly certificateArn?: string;
  /**
   * Pre-cutover DNS-only preparation: creates A/AAAA alias records to the
   * distribution WITHOUT attaching the domain or requiring a cert. Needs
   * hostedZoneId + hostedZoneName.
   */
  readonly dnsRecordName?: string;
  /** ISO 3166-1 alpha-2 codes; empty = no restriction (#616). */
  readonly geoRestrictionCountries?: string[];
}

export class AngularFrontend extends Construct {
  readonly cloudFrontWebDistribution: Distribution;
  readonly assetBucket: Bucket;
  /** Needed by budget-pacing IAM (#579). */
  readonly maintenanceModeStoreArn: string;
  private readonly certificate?: acm.ICertificate;
  private readonly hostedZone?: route53.IHostedZone;
  private readonly alternateDomainName?: string;

  constructor(scope: Construct, id: string, props: FrontendProps) {
    super(scope, id);

    this.alternateDomainName = props.alternateDomainName;

    const assetBucket = new Bucket(this, 'AssetBucket', {
      // Prod suffixes account id; demo still owns the pre-#473 historic name.
      bucketName:
        props.envName === 'prod'
          ? `${props.prefix}-assets-${props.envName}-${Stack.of(this).region}-${Stack.of(this).account}`
          : `${props.prefix}-assets-${props.envName}-${Stack.of(this).region}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      serverAccessLogsBucket: props.accessLogBucket,
      serverAccessLogsPrefix: 'frontend-assets',
    });

    if (props.alternateDomainName && props.hostedZoneId) {
      const zoneName =
        props.hostedZoneName ||
        this.getDomainZoneName(props.alternateDomainName);
      this.hostedZone = route53.HostedZone.fromHostedZoneAttributes(
        this,
        'HostedZone',
        {
          hostedZoneId: props.hostedZoneId,
          zoneName,
        },
      );

      this.certificate = props.certificateArn
        ? acm.Certificate.fromCertificateArn(
            this,
            'Certificate',
            props.certificateArn,
          )
        : new acm.Certificate(this, 'Certificate', {
            domainName: props.alternateDomainName,
            validation: acm.CertificateValidation.fromDns(this.hostedZone),
          });
    }

    const connectSrcExtras = [
      'https://www.deutsche-rentenversicherung.de',
      'https://cognito-idp.eu-central-1.amazonaws.com',
      ...(props.envName === 'dev'
        ? ['https://*.execute-api.eu-central-1.amazonaws.com']
        : []),
    ].join(' ');
    // Matomo loads dynamically via MatomoService; the external domain in
    // script-src covers matomo.js — no inline hash needed.
    const cspValue = [
      "default-src 'self'",
      `script-src 'self' https://www.deutsche-rentenversicherung.de`,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self'",
      `connect-src 'self' ${connectSrcExtras}`,
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "object-src 'none'",
      "form-action 'self'",
    ].join('; ');

    const responseHeadersPolicy = new ResponseHeadersPolicy(
      this,
      'SecurityHeadersPolicy',
      {
        securityHeadersBehavior: {
          contentSecurityPolicy: {
            contentSecurityPolicy: cspValue,
            override: true,
          },
          strictTransportSecurity: {
            accessControlMaxAge: Duration.days(365),
            includeSubdomains: true,
            override: true,
          },
          contentTypeOptions: { override: true },
          referrerPolicy: {
            referrerPolicy:
              HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
            override: true,
          },
          frameOptions: {
            frameOption: HeadersFrameOption.DENY,
            override: true,
          },
        },
        removeHeaders: ['Server'],
      },
    );

    const maintenanceModeStore = new KeyValueStore(
      this,
      'MaintenanceModeStore',
      {
        keyValueStoreName: `${props.prefix}-maintenance-${props.envName}`,
        comment: 'Holds the on/off flag read by the maintenance mode function',
        source: ImportSource.fromInline(
          JSON.stringify({ data: [{ key: 'maintenance', value: 'off' }] }),
        ),
      },
    );
    this.maintenanceModeStoreArn = maintenanceModeStore.keyValueStoreArn;

    const maintenanceModeFunction = new CloudFrontFunction(
      this,
      'MaintenanceModeFunction',
      {
        functionName: `${props.prefix}-maintenance-mode-${props.envName}`,
        comment:
          'SPA routing + maintenance mode: rewrites non-file requests to /index.html (or maintenance page when enabled)',
        runtime: FunctionRuntime.JS_2_0,
        keyValueStore: maintenanceModeStore,
        code: FunctionCode.fromInline(
          bundleCloudFrontFunctionCode(
            join(
              __dirname,
              'cloudfront-functions',
              'maintenance-mode.function.ts',
            ),
          ),
        ),
      },
    );

    const geoAllowlist = props.geoRestrictionCountries ?? [];

    const distribution = new Distribution(this, 'Distribution', {
      defaultRootObject: 'index.html',
      minimumProtocolVersion: SecurityPolicyProtocol.TLS_V1_2_2021,
      defaultBehavior: {
        origin: S3BucketOrigin.withOriginAccessControl(assetBucket),
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: CachePolicy.CACHING_OPTIMIZED,
        responseHeadersPolicy,
        functionAssociations: [
          {
            function: maintenanceModeFunction,
            eventType: FunctionEventType.VIEWER_REQUEST,
          },
        ],
      },
      ...(this.alternateDomainName && this.certificate
        ? {
            domainNames: [this.alternateDomainName],
            certificate: this.certificate,
          }
        : {}),
      ...(!this.shouldSkipAccessLogging() && {
        logBucket: props.accessLogBucket,
        logFilePrefix: 'AngularFrontend/',
      }),
      ...(geoAllowlist.length > 0
        ? { geoRestriction: GeoRestriction.allowlist(...geoAllowlist) }
        : {}),
      webAclId: props.webAclId,
      enableIpv6: props.enableIpV6,
    });

    if (this.alternateDomainName && this.hostedZone) {
      new route53.ARecord(this, 'AngularAliasRecord', {
        zone: this.hostedZone,
        target: route53.RecordTarget.fromAlias(
          new targets.CloudFrontTarget(distribution),
        ),
        recordName: this.alternateDomainName,
      });

      if (props.enableIpV6) {
        new route53.AaaaRecord(this, 'AngularAaaaRecord', {
          zone: this.hostedZone,
          target: route53.RecordTarget.fromAlias(
            new targets.CloudFrontTarget(distribution),
          ),
          recordName: this.alternateDomainName,
        });
      }
    }

    // Pre-cutover DNS-only path for non-delegated zones: alias records without
    // attaching the domain to CloudFront.
    if (
      props.dnsRecordName &&
      props.hostedZoneId &&
      !this.alternateDomainName
    ) {
      const dnsOnlyZoneName = props.hostedZoneName || props.dnsRecordName;
      const dnsOnlyZone = route53.HostedZone.fromHostedZoneAttributes(
        this,
        'DnsOnlyHostedZone',
        {
          hostedZoneId: props.hostedZoneId,
          zoneName: dnsOnlyZoneName,
        },
      );

      new route53.ARecord(this, 'DnsOnlyARecord', {
        zone: dnsOnlyZone,
        target: route53.RecordTarget.fromAlias(
          new targets.CloudFrontTarget(distribution),
        ),
        recordName: props.dnsRecordName,
      });

      if (props.enableIpV6) {
        new route53.AaaaRecord(this, 'DnsOnlyAaaaRecord', {
          zone: dnsOnlyZone,
          target: route53.RecordTarget.fromAlias(
            new targets.CloudFrontTarget(distribution),
          ),
          recordName: props.dnsRecordName,
        });
      }
    }

    if (geoAllowlist.length === 0) {
      NagSuppressions.addResourceSuppressions(distribution, [
        {
          id: 'AwsPrototyping-CloudFrontDistributionGeoRestrictions',
          reason:
            'Env opted out of geo restriction (geoRestrictionCountries=[]). See #616.',
        },
      ]);
    }

    this.assetBucket = assetBucket;
    this.cloudFrontWebDistribution = distribution;

    new CfnOutput(this, 'FrontendS3BucketName', {
      value: this.assetBucket.bucketName,
      description: 'S3 bucket for frontend assets',
    });

    if (this.alternateDomainName) {
      new CfnOutput(this, 'AlternateDomain', {
        value: this.alternateDomainName,
        description: 'Alternate domain name for the CloudFront distribution',
      });
    }
    if (this.certificate) {
      new CfnOutput(this, 'CertificateArn', {
        value: this.certificate.certificateArn,
        description: 'ARN of the ACM certificate',
      });
    }
    new CfnOutput(this, 'CloudFrontDistributionId', {
      value: distribution.distributionId,
      description: 'CloudFront Distribution ID',
    });

    new CfnOutput(this, 'CloudFrontDistributionUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'CloudFront Distribution URL',
      exportName: `${props.envName}-CloudFrontUrl`,
    });

    new CfnOutput(this, 'MaintenanceModeStoreArn', {
      value: maintenanceModeStore.keyValueStoreArn,
      description:
        'ARN of the CloudFront KeyValueStore holding the maintenance mode flag',
    });

    new CfnOutput(this, 'FrontendCloudFrontDistributionUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'CloudFront Distribution URL (for maintenance-switch)',
    });

    new CfnOutput(this, 'FrontendMaintenanceModeStoreArn', {
      value: maintenanceModeStore.keyValueStoreArn,
      description:
        'ARN of the CloudFront KeyValueStore holding the maintenance mode flag (for maintenance-switch)',
    });
  }

  /** 'chat.example.com' → 'example.com'. ccTLDs need hostedZoneName override. */
  private getDomainZoneName(domainName: string): string {
    const parts = domainName.split('.');
    if (parts.length <= 2) return domainName;
    return parts.slice(-2).join('.');
  }

  getOrigin(): string {
    if (this.alternateDomainName) {
      return `https://${this.alternateDomainName}`;
    }
    return `https://${this.cloudFrontWebDistribution.distributionDomainName}`;
  }

  /** Must be called after the API Gateway construct exists. */
  addApiBehaviors(apiDomain: string, stageName: string): void {
    const apiOrigin = new HttpOrigin(apiDomain, {
      originPath: `/${stageName}`,
    });

    const apiBehaviorOptions = {
      viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
      cachePolicy: CachePolicy.CACHING_DISABLED,
      originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
      allowedMethods: AllowedMethods.ALLOW_ALL,
    };

    this.cloudFrontWebDistribution.addBehavior(
      '/api/*',
      apiOrigin,
      apiBehaviorOptions,
    );
    this.cloudFrontWebDistribution.addBehavior(
      '/health',
      apiOrigin,
      apiBehaviorOptions,
    );
  }

  /** Regions where CloudFront refuses access log delivery. */
  private shouldSkipAccessLogging(): boolean {
    const skipLoggingRegions = [
      'af-south-1',
      'ap-east-1',
      'ap-south-2',
      'ap-southeast-3',
      'ap-southeast-4',
      'ca-west-1',
      'eu-south-1',
      'eu-south-2',
      'eu-central-2',
      'il-central-1',
      'me-central-1',
    ];
    return skipLoggingRegions.includes(Stack.of(this).region);
  }
}
