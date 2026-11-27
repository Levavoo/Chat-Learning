import { CfnOutput, Duration, Stack, RemovalPolicy } from 'aws-cdk-lib';
import {
  CfnUserPoolGroup,
  ProviderAttribute,
  UserPool,
  UserPoolClient,
  UserPoolOperation,
  UserPoolIdentityProviderOidc,
} from 'aws-cdk-lib/aws-cognito';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import * as path from 'path';
import { Idp, TIdentityProvider } from '../utils/identity-provider';
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import { CfnResource } from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface AuthProps {
  readonly prefix: string;
  readonly envName: string;
  readonly origin: string;
  readonly userPoolDomainPrefixKey: string;
  readonly idp: Idp;
  readonly allowedSignUpEmailDomains: string[];
  readonly selfSignUpEnabled: boolean;
  readonly tokenValidity: Duration;
  readonly webAclArn?: string;
}

export class Auth extends Construct {
  readonly userPool: UserPool;
  readonly client: UserPoolClient;
  constructor(scope: Construct, id: string, props: AuthProps) {
    super(scope, id);
    const userPool = new UserPool(this, 'UserPool', {
      userPoolName: `${props.prefix}-pool-${props.envName}`,
      passwordPolicy: {
        requireUppercase: true,
        requireSymbols: true,
        requireDigits: true,
        minLength: 8,
      },
      selfSignUpEnabled: props.selfSignUpEnabled && !props.idp.isExist(),
      signInAliases: {
        username: false,
        email: true,
      },
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const clientProps = (() => {
      const defaultProps = {
        idTokenValidity: props.tokenValidity,
        authFlows: {
          userPassword: true,
          userSrp: true,
        },
      };
      if (!props.idp.isExist()) return defaultProps;
      return {
        ...defaultProps,
        oAuth: {
          callbackUrls: [props.origin],
          logoutUrls: [props.origin],
        },
        supportedIdentityProviders: [
          ...props.idp.getSupportedIndetityProviders(),
        ],
      };
    })();

    const client = userPool.addClient(`Client`, clientProps);

    const configureProvider = (
      provider: TIdentityProvider,
      userPool: UserPool,
      client: UserPoolClient,
    ) => {
      const secret = secretsmanager.Secret.fromSecretNameV2(
        this,
        `Secret-${provider.secretName}`,
        provider.secretName,
      );

      const clientIdValue = secret.secretValueFromJson('clientId');
      if (!clientIdValue) {
        throw new Error(
          `Secret '${provider.secretName}' must contain 'clientId' field`,
        );
      }
      const clientId = clientIdValue.unsafeUnwrap().toString();

      const clientSecretValue = secret.secretValueFromJson('clientSecret');
      if (!clientSecretValue) {
        throw new Error(
          `Secret '${provider.secretName}' must contain 'clientSecret' field`,
        );
      }

      switch (provider.service) {
        case 'oidc': {
          const issuerUrlValue = secret.secretValueFromJson('issuerUrl');
          if (!issuerUrlValue) {
            throw new Error(
              `Secret '${provider.secretName}' must contain 'issuerUrl' field for OIDC provider`,
            );
          }
          const issuerUrl = issuerUrlValue.unsafeUnwrap().toString();
          const clientSecret = clientSecretValue.unsafeUnwrap().toString();

          const oidcProvider = new UserPoolIdentityProviderOidc(
            this,
            `OidcProvider-${provider.secretName}`,
            {
              name: provider.serviceName,
              userPool,
              clientId,
              clientSecret,
              issuerUrl,
              attributeMapping: {
                email: ProviderAttribute.other('EMAIL'),
              },
              scopes: ['openid', 'email'],
            },
          );
          client.node.addDependency(oidcProvider);
          break;
        }
      }
    };

    if (props.idp.isExist()) {
      for (const provider of props.idp.getProviders()) {
        configureProvider(provider, userPool, client);
      }

      userPool.addDomain('UserPool', {
        cognitoDomain: {
          domainPrefix: props.userPoolDomainPrefixKey,
        },
      });
    }

    if (props.allowedSignUpEmailDomains.length >= 1) {
      const checkEmailDomainFunctionName = `${props.prefix}-email-check-${props.envName}`;
      const checkEmailDomainLogGroup = new logs.LogGroup(
        this,
        'EmailCheckLogGroup',
        {
          logGroupName: `/aws/lambda/${checkEmailDomainFunctionName}`,
          retention: logs.RetentionDays.THREE_MONTHS,
          removalPolicy: RemovalPolicy.DESTROY,
        },
      );

      const region = Stack.of(this).region;
      const account = Stack.of(this).account;

      const emailCheckRole = new iam.Role(this, 'EmailCheckRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        description: `Execution role for ${checkEmailDomainFunctionName}`,
      });

      emailCheckRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            'logs:CreateLogGroup',
            'logs:CreateLogStream',
            'logs:PutLogEvents',
          ],
          resources: [
            `arn:aws:logs:${region}:${account}:log-group:/aws/lambda/${checkEmailDomainFunctionName}:*`,
          ],
        }),
      );

      const powertoolsLayerArn = ssm.StringParameter.valueForStringParameter(
        this,
        '/aws/service/powertools/python/x86_64/python3.13/latest',
      );

      const checkEmailDomainFunction = new lambda.Function(
        this,
        'EmailCheckFn',
        {
          functionName: checkEmailDomainFunctionName,
          description:
            'Pre-signup trigger to validate email domains against allowed list',
          runtime: lambda.Runtime.PYTHON_3_13,
          architecture: lambda.Architecture.X86_64,
          handler: 'check_email_domain.handler',
          code: lambda.Code.fromAsset(
            path.join(__dirname, '../../../backend/src/auth_handler/'),
          ),
          layers: [
            lambda.LayerVersion.fromLayerVersionArn(
              this,
              'PowertoolsLayer',
              powertoolsLayerArn,
            ),
          ],
          timeout: Duration.minutes(1),
          environment: {
            ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR: JSON.stringify(
              props.allowedSignUpEmailDomains,
            ),
          },
          logGroup: checkEmailDomainLogGroup,
          role: emailCheckRole,
        },
      );

      userPool.addTrigger(
        UserPoolOperation.PRE_SIGN_UP,
        checkEmailDomainFunction,
      );
    }

    if (props.webAclArn) {
      const cognitoWebAclAssociation = new wafv2.CfnWebACLAssociation(
        this,
        'CognitoWebAclAssociation',
        {
          resourceArn: userPool.userPoolArn,
          webAclArn: props.webAclArn,
        },
      );
      cognitoWebAclAssociation.addDependency(
        userPool.node.defaultChild as CfnResource,
      );
    }

    this.client = client;
    this.userPool = userPool;

    // RFC-0009 dashboard-admins group. Pre-existing manual groups must be
    // deleted or `cdk import`ed before deploying.
    new CfnUserPoolGroup(this, 'DashboardAdminsGroup', {
      groupName: 'dashboard-admins',
      userPoolId: userPool.userPoolId,
      description: 'Redakteure mit Zugriff auf das Analytics-Dashboard',
    });

    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: client.userPoolClientId });
    if (props.idp.isExist())
      new CfnOutput(this, 'ApprovedRedirectURI', {
        value: `https://${props.userPoolDomainPrefixKey}.auth.${
          Stack.of(userPool).region
        }.amazoncognito.com/oauth2/idpresponse`,
      });
  }
}
