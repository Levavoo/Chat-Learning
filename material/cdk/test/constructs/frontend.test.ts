import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { AngularFrontend } from '../../lib/constructs/frontend';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import * as fs from 'fs';
import * as path from 'path';

describe('AngularFrontend Construct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;
  let accessLogBucket: Bucket;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });

    accessLogBucket = new Bucket(stack, 'AccessLogBucket', {
      bucketName: 'test-access-logs',
    });
  });

  afterEach(() => {
    const tmpDir = '/tmp';
    try {
      const files = fs.readdirSync(tmpDir);
      files.forEach((file) => {
        if (file.startsWith('cdk-custom-resource')) {
          const filePath = path.join(tmpDir, file);
          try {
            fs.rmSync(filePath, { recursive: true, force: true });
          } catch (err) {
            // ignore
          }
        }
      });
    } catch (err) {
      // ignore
    }
  });

  describe('S3 Asset Bucket', () => {
    test('should create asset bucket with correct name', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: 'test-assets-dev-eu-central-1',
      });
    });

    test('should enable encryption on asset bucket', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: 'test-assets-dev-eu-central-1',
        BucketEncryption: {
          ServerSideEncryptionConfiguration: [
            {
              ServerSideEncryptionByDefault: {
                SSEAlgorithm: 'AES256',
              },
            },
          ],
        },
      });
    });

    test('should block public access on asset bucket', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: 'test-assets-dev-eu-central-1',
        PublicAccessBlockConfiguration: {
          BlockPublicAcls: true,
          BlockPublicPolicy: true,
          IgnorePublicAcls: true,
          RestrictPublicBuckets: true,
        },
      });
    });

    test('should configure access logging when bucket provided', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        accessLogBucket,
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: 'test-assets-dev-eu-central-1',
        LoggingConfiguration: Match.objectLike({
          LogFilePrefix: 'frontend-assets',
        }),
      });
    });
  });

  describe('CloudFront Distribution', () => {
    test('should create CloudFront distribution', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::CloudFront::Distribution', 1);
    });

    test('should configure S3 origin with OAC', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          DefaultRootObject: 'index.html',
          Enabled: true,
        },
      });
    });

    test('should redirect HTTP to HTTPS', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          DefaultCacheBehavior: {
            ViewerProtocolPolicy: 'redirect-to-https',
          },
        },
      });
    });

    test('should enable IPv6 when configured', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          IPV6Enabled: true,
        },
      });
    });

    test('should disable IPv6 when configured', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: false,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          IPV6Enabled: false,
        },
      });
    });

    test('should use CloudFront Function for SPA routing instead of error responses', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Function', {
        FunctionConfig: {
          Runtime: 'cloudfront-js-2.0',
        },
      });
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.not(
          Match.objectLike({
            CustomErrorResponses: Match.anyValue(),
          }),
        ),
      });
    });

    test('should attach WAF Web ACL', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          WebACLId: 'test-web-acl-id',
        },
      });
    });

    test('should configure access logging when bucket provided', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        accessLogBucket,
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          Logging: Match.objectLike({
            Prefix: 'AngularFrontend/',
          }),
        },
      });
    });
  });

  describe('Geo Restriction (#616)', () => {
    test('should configure allowlist when geoRestrictionCountries is set', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'qa',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        geoRestrictionCountries: ['DE', 'AT', 'CH'],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          Restrictions: {
            GeoRestriction: {
              RestrictionType: 'whitelist',
              Locations: ['DE', 'AT', 'CH'],
            },
          },
        },
      });
    });

    test('should omit Restrictions when geoRestrictionCountries is empty', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        geoRestrictionCountries: [],
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          Restrictions: Match.absent(),
        }),
      });
    });

    test('should omit Restrictions when geoRestrictionCountries is undefined', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          Restrictions: Match.absent(),
        }),
      });
    });
  });

  describe('Custom Domain Configuration', () => {
    test('should create ACM certificate when alternate domain provided', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CertificateManager::Certificate', {
        DomainName: 'chat.example.com',
        ValidationMethod: 'DNS',
      });
    });

    test('should configure CloudFront with alternate domain', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          Aliases: ['chat.example.com'],
        },
      });
    });

    test('should create Route53 A record for alternate domain', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Route53::RecordSet', {
        Type: 'A',
        Name: 'chat.example.com.',
      });
    });

    test('should create Route53 AAAA record when IPv6 enabled', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Route53::RecordSet', {
        Type: 'AAAA',
        Name: 'chat.example.com.',
      });
    });

    test('should not create AAAA record when IPv6 disabled', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: false,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      const aaaaRecords = template.findResources('AWS::Route53::RecordSet', {
        Properties: {
          Type: 'AAAA',
        },
      });
      expect(Object.keys(aaaaRecords).length).toBe(0);
    });

    test('should not create certificate without alternate domain', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const certificates = template.findResources(
        'AWS::CertificateManager::Certificate',
      );
      expect(Object.keys(certificates).length).toBe(0);
    });
  });

  describe('Origin Access Control', () => {
    test('should create Origin Access Control', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::CloudFront::OriginAccessControl', 1);
    });

    test('should configure bucket policy for OAC', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::S3::BucketPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 's3:GetObject',
              Effect: 'Allow',
              Principal: {
                Service: 'cloudfront.amazonaws.com',
              },
            }),
          ]),
        },
      });
    });
  });

  describe('Security Headers Policy', () => {
    test('should create ResponseHeadersPolicy', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::CloudFront::ResponseHeadersPolicy', 1);
    });

    test('should configure HSTS without preload', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::ResponseHeadersPolicy', {
        ResponseHeadersPolicyConfig: {
          SecurityHeadersConfig: {
            StrictTransportSecurity: {
              AccessControlMaxAgeSec: 31536000,
              IncludeSubdomains: true,
              Override: true,
            },
          },
        },
      });
    });

    test('should configure X-Content-Type-Options, Referrer-Policy, X-Frame-Options', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::ResponseHeadersPolicy', {
        ResponseHeadersPolicyConfig: {
          SecurityHeadersConfig: {
            ContentTypeOptions: { Override: true },
            ReferrerPolicy: {
              ReferrerPolicy: 'strict-origin-when-cross-origin',
              Override: true,
            },
            FrameOptions: {
              FrameOption: 'DENY',
              Override: true,
            },
          },
        },
      });
    });

    test('should attach ResponseHeadersPolicy to default cache behavior', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          DefaultCacheBehavior: {
            ResponseHeadersPolicyId: Match.anyValue(),
          },
        },
      });
    });

    test('should include enforced CSP header with default origins', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::ResponseHeadersPolicy', {
        ResponseHeadersPolicyConfig: {
          SecurityHeadersConfig: Match.objectLike({
            ContentSecurityPolicy: Match.objectLike({
              Override: true,
            }),
          }),
          RemoveHeadersConfig: {
            Items: Match.arrayWith([Match.objectLike({ Header: 'Server' })]),
          },
        },
      });
    });

    test('should include execute-api wildcard in CSP connect-src for dev', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const policies = template.findResources(
        'AWS::CloudFront::ResponseHeadersPolicy',
      );
      const policyValues = Object.values(policies);
      expect(policyValues.length).toBe(1);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const policy = policyValues[0] as any;
      const cspValue =
        policy.Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig
          .ContentSecurityPolicy.ContentSecurityPolicy;
      expect(cspValue).toContain(
        'https://*.execute-api.eu-central-1.amazonaws.com',
      );
      expect(cspValue).toContain("'self'");
    });

    test.each(['qa', 'preprod', 'prod', 'demo'])(
      'should NOT include execute-api wildcard in CSP connect-src for %s',
      (envName) => {
        new AngularFrontend(stack, 'TestFrontend', {
          prefix: 'test',
          envName,
          enableIpV6: true,
        });

        template = Template.fromStack(stack);
        const policies = template.findResources(
          'AWS::CloudFront::ResponseHeadersPolicy',
        );
        const policyValues = Object.values(policies);
        expect(policyValues.length).toBe(1);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const policy = policyValues[0] as any;
        const cspValue =
          policy.Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig
            .ContentSecurityPolicy.ContentSecurityPolicy;
        expect(cspValue).not.toContain('execute-api');
      },
    );

    test('should NOT include unsafe-inline in CSP script-src', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const policies = template.findResources(
        'AWS::CloudFront::ResponseHeadersPolicy',
      );
      const policyValues = Object.values(policies);
      expect(policyValues.length).toBe(1);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const policy = policyValues[0] as any;
      const cspValue =
        policy.Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig
          .ContentSecurityPolicy.ContentSecurityPolicy;
      const scriptSrc = cspValue
        .split(';')
        .find((d: string) => d.trim().startsWith('script-src'));
      expect(scriptSrc).toBeDefined();
      expect(scriptSrc).not.toContain("'unsafe-inline'");
    });

    test('should NOT include sha256 hash in CSP script-src (no inline scripts)', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const policies = template.findResources(
        'AWS::CloudFront::ResponseHeadersPolicy',
      );
      const policyValues = Object.values(policies);
      expect(policyValues.length).toBe(1);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const policy = policyValues[0] as any;
      const cspValue =
        policy.Properties.ResponseHeadersPolicyConfig.SecurityHeadersConfig
          .ContentSecurityPolicy.ContentSecurityPolicy;
      const scriptSrc = cspValue
        .split(';')
        .find((d: string) => d.trim().startsWith('script-src'));
      expect(scriptSrc).toBeDefined();
      expect(scriptSrc).not.toMatch(/'sha256-[A-Za-z0-9+/=]+'/);
      expect(scriptSrc).toContain('https://www.deutsche-rentenversicherung.de');
    });
  });

  describe('TLS minimum protocol version', () => {
    test('should set TLS 1.2 minimum when custom cert present', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          ViewerCertificate: {
            MinimumProtocolVersion: 'TLSv1.2_2021',
          },
        },
      });
    });
  });

  describe('Maintenance Mode', () => {
    test('should create a CloudFront KeyValueStore', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::CloudFront::KeyValueStore', 1);
    });

    test('should create a CloudFront Function on the JS 2.0 runtime associated with the KeyValueStore', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const kvsResources = template.findResources(
        'AWS::CloudFront::KeyValueStore',
      );
      const kvsLogicalId = Object.keys(kvsResources)[0];

      template.hasResourceProperties('AWS::CloudFront::Function', {
        FunctionConfig: Match.objectLike({
          Runtime: 'cloudfront-js-2.0',
          KeyValueStoreAssociations: Match.arrayWith([
            Match.objectLike({
              KeyValueStoreARN: {
                'Fn::GetAtt': Match.arrayWith([kvsLogicalId]),
              },
            }),
          ]),
        }),
      });
    });

    test('should deploy function code that is loadable by the CloudFront Functions JS 2.0 runtime', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const functionResources = template.findResources(
        'AWS::CloudFront::Function',
      );
      const functionCode = Object.values(functionResources)[0].Properties
        .FunctionCode as string;

      // CloudFront Functions JS 2.0 has no CommonJS globals (exports/require/module),
      // so a tsc-emitted CJS wrapper throws a ReferenceError before the handler runs.
      expect(functionCode).not.toContain('exports.');
      expect(functionCode).not.toContain('Object.defineProperty(exports');
      expect(functionCode).not.toContain('require(');
      expect(functionCode).toMatch(/from\s+["']cloudfront["']/);
    });

    test('should associate the maintenance function with the default behavior on viewer-request', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: {
          DefaultCacheBehavior: Match.objectLike({
            FunctionAssociations: Match.arrayWith([
              Match.objectLike({
                EventType: 'viewer-request',
              }),
            ]),
          }),
        },
      });
    });

    test('should not use distribution-level error responses (SPA routing handled by CF function)', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          CustomErrorResponses: Match.absent(),
        }),
      });
    });

    test('should output the maintenance KeyValueStore ARN', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description:
          'ARN of the CloudFront KeyValueStore holding the maintenance mode flag',
      });
    });
  });

  // Maintenance asset deployment previously tested against NodejsBuild's
  // buildCommands (#648 MR1). The Angular build moved to GitLab CI; the
  // maintenance-assets copy step is now covered by
  // .gitlab/ci/scripts/tests/deploy/deploy-frontend.bats.

  describe('Maintenance page markup', () => {
    const maintenanceHtmlPath = path.join(
      __dirname,
      '../../../drv-frontend/src/maintenance-page/index.html',
    );

    // The CloudFront function rewrites the *origin* fetch to /_maintenance/index.html
    // without a redirect, so the browser's address bar (and therefore relative-URL
    // resolution) stays on whatever page the user actually requested. A <base> tag
    // anchors the page's own relative asset resolution to /_maintenance/ regardless.
    // The CloudFront function rewrites the origin fetch to /_maintenance/index.html
    // without a redirect, so the address bar stays on whatever page the user
    // requested; <base> anchors the page's own relative asset resolution.
    test('anchors relative asset resolution to /_maintenance/', () => {
      const html = fs.readFileSync(maintenanceHtmlPath, 'utf-8');
      expect(html).toContain('<base href="/_maintenance/" />');
    });

    test('references its CSS and icon with absolute /_maintenance/ paths', () => {
      const html = fs.readFileSync(maintenanceHtmlPath, 'utf-8');
      expect(html).toContain('href="/_maintenance/maintenance.css"');
      expect(html).toContain('href="/_maintenance/maintenance.svg"');
      expect(html).toContain('src="/_maintenance/maintenance.svg"');
    });
  });

  describe('Getter Methods', () => {
    test('should return CloudFront domain when no alternate domain', () => {
      const frontend = new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
      });

      const origin = frontend.getOrigin();
      expect(origin).toBeDefined();
      expect(origin).toContain('https://');
      // During testing, CDK tokens are not resolved, so we just verify it's a token
      expect(origin).toMatch(/Token/i);
    });

    test('should return alternate domain when configured', () => {
      const frontend = new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      const origin = frontend.getOrigin();
      expect(origin).toBe('https://chat.example.com');
    });
  });

  describe('Outputs', () => {
    test('should output alternate domain when configured', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'Alternate domain name for the CloudFront distribution',
      });
    });

    test('should output certificate ARN when configured', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        webAclId: 'test-web-acl-id',
        enableIpV6: true,
        alternateDomainName: 'chat.example.com',
        hostedZoneId: 'Z1234567890ABC',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Description: 'ARN of the ACM certificate',
      });
    });
  });

  describe('DNS-only preparation records (pre-cutover)', () => {
    test('should create A alias record when dnsRecordName and hostedZoneId are set', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Route53::RecordSet', {
        Type: 'A',
        Name: 'rentenchat.deutsche-rentenversicherung.de.',
        HostedZoneId: 'Z0360847NAVF7FXXP098',
      });
    });

    test('should create AAAA alias record when dnsRecordName set and IPv6 enabled', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Route53::RecordSet', {
        Type: 'AAAA',
        Name: 'rentenchat.deutsche-rentenversicherung.de.',
        HostedZoneId: 'Z0360847NAVF7FXXP098',
      });
    });

    test('should NOT create AAAA record when IPv6 is disabled', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: false,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      const aaaaRecords = template.findResources('AWS::Route53::RecordSet', {
        Properties: {
          Type: 'AAAA',
        },
      });
      expect(Object.keys(aaaaRecords).length).toBe(0);
    });

    test('should NOT attach alternate domain or certificate to CloudFront in DNS-only mode', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      // No Aliases on CloudFront
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          Aliases: Match.absent(),
        }),
      });
      // No ViewerCertificate with ACM cert
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          ViewerCertificate: Match.absent(),
        }),
      });
    });

    test('should NOT create an ACM certificate in DNS-only mode', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      const certificates = template.findResources(
        'AWS::CertificateManager::Certificate',
      );
      expect(Object.keys(certificates).length).toBe(0);
    });

    test('should NOT create DNS-only records when alternateDomainName is also set', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'preprod',
        enableIpV6: true,
        alternateDomainName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z08197181YLWUAZDZBJQ',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
        certificateArn:
          'arn:aws:acm:us-east-1:271033482134:certificate/d78e46f6-f2c4-4ba5-91e6-1c4bf4c1a426',
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      const allRecordSets = template.findResources('AWS::Route53::RecordSet');
      const logicalIds = Object.keys(allRecordSets);
      expect(logicalIds.some((id) => id.includes('AngularAliasRecord'))).toBe(
        true,
      );
      expect(logicalIds.some((id) => id.includes('AngularAaaaRecord'))).toBe(
        true,
      );
      expect(logicalIds.some((id) => id.includes('DnsOnly'))).toBe(false);
    });

    test('should NOT create DNS-only records when neither dnsRecordName nor hostedZoneId is set', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'dev',
        enableIpV6: true,
      });

      template = Template.fromStack(stack);
      const allRecordSets = template.findResources('AWS::Route53::RecordSet');
      expect(Object.keys(allRecordSets).length).toBe(0);
    });

    test('DNS-only records use distinct logical IDs from alternate-domain records', () => {
      // DNS-only mode
      const dnsOnlyApp = new App();
      const dnsOnlyStack = new Stack(dnsOnlyApp, 'DnsOnlyStack', {
        env: { account: '718036735727', region: 'eu-central-1' },
      });
      new AngularFrontend(dnsOnlyStack, 'TestFrontend', {
        prefix: 'renate',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });
      const dnsOnlyTemplate = Template.fromStack(dnsOnlyStack);
      const dnsOnlyRecords = dnsOnlyTemplate.findResources(
        'AWS::Route53::RecordSet',
      );
      const dnsOnlyIds = Object.keys(dnsOnlyRecords);

      // Alternate-domain mode (preprod)
      const altDomainApp = new App();
      const altDomainStack = new Stack(altDomainApp, 'AltDomainStack', {
        env: { account: '271033482134', region: 'eu-central-1' },
      });
      new AngularFrontend(altDomainStack, 'TestFrontend', {
        prefix: 'renate',
        envName: 'preprod',
        enableIpV6: true,
        alternateDomainName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z08197181YLWUAZDZBJQ',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
        certificateArn:
          'arn:aws:acm:us-east-1:271033482134:certificate/d78e46f6-f2c4-4ba5-91e6-1c4bf4c1a426',
      });
      const altDomainTemplate = Template.fromStack(altDomainStack);
      const altDomainRecords = altDomainTemplate.findResources(
        'AWS::Route53::RecordSet',
      );
      const altDomainIds = Object.keys(altDomainRecords);

      // DNS-only IDs contain "DnsOnly", alternate-domain IDs contain "Angular"
      expect(dnsOnlyIds.every((id) => id.includes('DnsOnly'))).toBe(true);
      expect(altDomainIds.every((id) => id.includes('Angular'))).toBe(true);

      // No overlap
      const overlap = dnsOnlyIds.filter((id) => altDomainIds.includes(id));
      expect(overlap).toHaveLength(0);
    });

    test('DNS-only A record is an alias to CloudFront distribution', () => {
      new AngularFrontend(stack, 'TestFrontend', {
        prefix: 'test',
        envName: 'prod',
        enableIpV6: true,
        dnsRecordName: 'rentenchat.deutsche-rentenversicherung.de',
        hostedZoneId: 'Z0360847NAVF7FXXP098',
        hostedZoneName: 'rentenchat.deutsche-rentenversicherung.de',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Route53::RecordSet', {
        Type: 'A',
        Name: 'rentenchat.deutsche-rentenversicherung.de.',
        AliasTarget: Match.objectLike({
          HostedZoneId: Match.anyValue(),
          DNSName: Match.anyValue(),
        }),
      });
    });
  });
});
