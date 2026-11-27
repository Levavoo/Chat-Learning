import { Construct } from 'constructs';
import { CfnOutput, RemovalPolicy, Tags } from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface NetworkingProps {
  readonly prefix: string;
  /** @default 10.0.0.0/16 */
  readonly vpcCidr?: string;
  /** @default 2 */
  readonly maxAzs?: number;
  /** 1 = cost-optimized (shared NAT); 2+ = HA per AZ. @default 1 */
  readonly natGateways?: number;
  /** @default true */
  readonly enableFlowLogs?: boolean;
  readonly envName: string;
  readonly tags?: Record<string, string>;
}

export class Networking extends Construct {
  readonly vpc: ec2.Vpc;
  readonly lambdaSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkingProps) {
    super(scope, id);

    const vpc = new ec2.Vpc(this, 'Vpc', {
      vpcName: `${props.prefix}-vpc-${props.envName}`,
      ipAddresses: ec2.IpAddresses.cidr(props.vpcCidr || '10.0.0.0/16'),
      maxAzs: props.maxAzs || 2,
      natGateways: props.natGateways || 1,
      subnetConfiguration: [
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    const lambdaSecurityGroup = new ec2.SecurityGroup(this, 'LambdaSg', {
      securityGroupName: `${props.prefix}-lambda-sg-${props.envName}`,
      vpc,
      description: 'Security group for Lambda functions in VPC',
      allowAllOutbound: false,
    });
    lambdaSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'Allow HTTPS outbound for AWS API calls and external services',
    );
    lambdaSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(80),
      'Allow HTTP outbound for external services',
    );
    lambdaSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.udp(53),
      'Allow DNS queries for name resolution',
    );
    lambdaSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(53),
      'Allow DNS queries over TCP for name resolution',
    );

    vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [
        {
          subnets: vpc.privateSubnets,
        },
      ],
    });

    if (props.enableFlowLogs !== false) {
      const flowLogGroup = new logs.LogGroup(this, 'FlowLogGroup', {
        logGroupName: `/aws/vpc/${props.prefix}-flowlogs-${props.envName}`,
        retention: logs.RetentionDays.THREE_MONTHS,
        removalPolicy: RemovalPolicy.DESTROY,
      });

      const flowLogRole = new iam.Role(this, 'FlowLogRole', {
        roleName: `${props.prefix}-vpc-flowlog-role-${props.envName}`,
        assumedBy: new iam.ServicePrincipal('vpc-flow-logs.amazonaws.com'),
      });

      new ec2.FlowLog(this, 'VpcFlowLog', {
        resourceType: ec2.FlowLogResourceType.fromVpc(vpc),
        destination: ec2.FlowLogDestination.toCloudWatchLogs(
          flowLogGroup,
          flowLogRole,
        ),
        trafficType: ec2.FlowLogTrafficType.ALL,
      });

      new CfnOutput(this, 'FlowLogGroupName', {
        value: flowLogGroup.logGroupName,
        description: 'CloudWatch Log Group for VPC Flow Logs',
      });
    }

    if (props.envName) {
      Tags.of(vpc).add('Environment', props.envName);
    }

    const projectTag = props.tags?.['Project'] || 'DigiBro-Chatbot';
    const managedByTag = props.tags?.['ManagedBy'] || 'CDK';

    Tags.of(vpc).add('Project', projectTag);
    Tags.of(vpc).add('ManagedBy', managedByTag);

    if (props.tags) {
      Object.entries(props.tags).forEach(([key, value]) => {
        if (key !== 'Project' && key !== 'ManagedBy') {
          Tags.of(vpc).add(key, value);
        }
      });
    }

    this.vpc = vpc;
    this.lambdaSecurityGroup = lambdaSecurityGroup;

    new CfnOutput(this, 'VpcId', {
      value: vpc.vpcId,
      description: 'VPC ID for the Chatbot infrastructure',
      exportName: `${props.envName || 'default'}-VpcId`,
    });

    new CfnOutput(this, 'VpcCidr', {
      value: vpc.vpcCidrBlock,
      description: 'CIDR block of the VPC',
    });

    new CfnOutput(this, 'PrivateSubnetIds', {
      value: vpc.privateSubnets.map((subnet) => subnet.subnetId).join(','),
      description: 'Comma-separated list of private subnet IDs',
      exportName: `${props.envName || 'default'}-PrivateSubnetIds`,
    });

    new CfnOutput(this, 'PublicSubnetIds', {
      value: vpc.publicSubnets.map((subnet) => subnet.subnetId).join(','),
      description: 'Comma-separated list of public subnet IDs',
      exportName: `${props.envName || 'default'}-PublicSubnetIds`,
    });

    new CfnOutput(this, 'LambdaSecurityGroupId', {
      value: lambdaSecurityGroup.securityGroupId,
      description: 'Security Group ID for Lambda functions',
      exportName: `${props.envName || 'default'}-LambdaSecurityGroupId`,
    });

    new CfnOutput(this, 'AvailabilityZones', {
      value: vpc.availabilityZones.join(','),
      description: 'Availability Zones used by the VPC',
    });
  }

  getVpc(): ec2.IVpc {
    return this.vpc;
  }

  getLambdaSecurityGroup(): ec2.ISecurityGroup {
    return this.lambdaSecurityGroup;
  }

  getPrivateSubnets(): ec2.ISubnet[] {
    return this.vpc.privateSubnets;
  }

  getPublicSubnets(): ec2.ISubnet[] {
    return this.vpc.publicSubnets;
  }
}
