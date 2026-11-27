import { App, Stack } from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { Networking } from '../../lib/constructs/networking';

describe('Networking Construct', () => {
  let app: App;
  let stack: Stack;
  let template: Template;

  beforeEach(() => {
    app = new App();
    stack = new Stack(app, 'TestStack', {
      env: { account: '123456789012', region: 'eu-central-1' },
    });
  });

  describe('VPC Creation', () => {
    test('should create VPC with default CIDR', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '10.0.0.0/16',
        EnableDnsHostnames: true,
        EnableDnsSupport: true,
      });
    });

    test('should create VPC with custom CIDR', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
        vpcCidr: '172.16.0.0/16',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '172.16.0.0/16',
      });
    });

    test('should tag VPC correctly', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      const vpcs = template.findResources('AWS::EC2::VPC');
      Object.values(vpcs).forEach((vpc: any) => {
        const tags = vpc.Properties.Tags;
        const tagMap = Object.fromEntries(
          tags.map((t: any) => [t.Key, t.Value]),
        );
        expect(tagMap.Environment).toBe('dev');
        expect(tagMap.Project).toBe('DigiBro-Chatbot');
        expect(tagMap.ManagedBy).toBe('CDK');
      });
    });
  });

  describe('Subnet Configuration', () => {
    test('should create public subnets', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::Subnet', {
        MapPublicIpOnLaunch: true,
      });
    });

    test('should create private subnets with egress', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::Subnet', {
        MapPublicIpOnLaunch: false,
      });
    });

    test('should distribute subnets across AZs', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
        maxAzs: 3,
      });

      template = Template.fromStack(stack);
      const subnets = template.findResources('AWS::EC2::Subnet');
      expect(Object.keys(subnets).length).toBeGreaterThanOrEqual(6); // 3 AZs * 2 types
    });
  });

  describe('NAT Gateway Configuration', () => {
    test('should create single NAT gateway by default', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::EC2::NatGateway', 1);
    });

    test('should create multiple NAT gateways for HA', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
        maxAzs: 2,
        natGateways: 2,
      });

      template = Template.fromStack(stack);
      template.resourceCountIs('AWS::EC2::NatGateway', 2);
    });

    test('should create EIP for NAT gateway', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::EIP', {
        Domain: 'vpc',
      });
    });
  });

  describe('Security Group Configuration', () => {
    test('should create Lambda security group', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        GroupDescription: 'Security group for Lambda functions in VPC',
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            CidrIp: '0.0.0.0/0',
            IpProtocol: 'tcp',
            FromPort: 443,
            ToPort: 443,
            Description:
              'Allow HTTPS outbound for AWS API calls and external services',
          }),
        ]),
      });
    });

    test('should allow HTTP egress', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            CidrIp: '0.0.0.0/0',
            IpProtocol: 'tcp',
            FromPort: 80,
            ToPort: 80,
            Description: 'Allow HTTP outbound for external services',
          }),
        ]),
      });
    });

    test('should allow DNS egress on UDP', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            CidrIp: '0.0.0.0/0',
            IpProtocol: 'udp',
            FromPort: 53,
            ToPort: 53,
            Description: 'Allow DNS queries for name resolution',
          }),
        ]),
      });
    });

    test('should allow DNS egress on TCP', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            CidrIp: '0.0.0.0/0',
            IpProtocol: 'tcp',
            FromPort: 53,
            ToPort: 53,
            Description: 'Allow DNS queries over TCP for name resolution',
          }),
        ]),
      });
    });

    test('should not allow all outbound by default', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      const securityGroups = template.findResources('AWS::EC2::SecurityGroup', {
        Properties: {
          GroupDescription: 'Security group for Lambda functions in VPC',
        },
      });

      Object.values(securityGroups).forEach((sg: any) => {
        const egressRules = sg.Properties.SecurityGroupEgress;
        const hasAllTraffic = egressRules.some(
          (rule: any) =>
            rule.CidrIp === '0.0.0.0/0' && rule.IpProtocol === '-1',
        );
        expect(hasAllTraffic).toBe(false);
      });
    });
  });

  describe('VPC Endpoints', () => {
    test('should create S3 gateway endpoint', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: Match.objectLike({
          'Fn::Join': Match.arrayWith([
            Match.arrayWith([Match.stringLikeRegexp('.*s3')]),
          ]),
        }),
        VpcEndpointType: 'Gateway',
      });
    });
  });

  describe('VPC Flow Logs', () => {
    test('should enable flow logs by default', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/vpc/test-flowlogs-dev',
        RetentionInDays: 90,
      });
    });

    test('should create flow log', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::EC2::FlowLog', {
        TrafficType: 'ALL',
      });
    });

    test('should create IAM role for flow logs', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasResourceProperties('AWS::IAM::Role', {
        RoleName: 'test-vpc-flowlog-role-dev',
      });
    });

    test('should skip flow logs when disabled', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
        enableFlowLogs: false,
      });

      template = Template.fromStack(stack);
      const flowLogs = template.findResources('AWS::EC2::FlowLog');
      expect(Object.keys(flowLogs).length).toBe(0);
    });
  });

  describe('Outputs', () => {
    test('should export VPC ID', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Export: { Name: 'dev-VpcId' },
      });
    });

    test('should export private subnet IDs', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Export: { Name: 'dev-PrivateSubnetIds' },
      });
    });

    test('should export public subnet IDs', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Export: { Name: 'dev-PublicSubnetIds' },
      });
    });

    test('should export Lambda security group ID', () => {
      new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      template = Template.fromStack(stack);
      template.hasOutput('*', {
        Export: { Name: 'dev-LambdaSecurityGroupId' },
      });
    });
  });

  describe('Getter Methods', () => {
    test('should return VPC instance', () => {
      const networking = new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      const vpc = networking.getVpc();
      expect(vpc).toBeDefined();
      expect(vpc.vpcId).toBeDefined();
    });

    test('should return security group', () => {
      const networking = new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      const sg = networking.getLambdaSecurityGroup();
      expect(sg).toBeDefined();
      expect(sg.securityGroupId).toBeDefined();
    });

    test('should return private subnets', () => {
      const networking = new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      const subnets = networking.getPrivateSubnets();
      expect(subnets).toBeDefined();
      expect(subnets.length).toBeGreaterThan(0);
    });

    test('should return public subnets', () => {
      const networking = new Networking(stack, 'TestNetworking', {
        prefix: 'test',
        envName: 'dev',
      });

      const subnets = networking.getPublicSubnets();
      expect(subnets).toBeDefined();
      expect(subnets.length).toBeGreaterThan(0);
    });
  });
});
