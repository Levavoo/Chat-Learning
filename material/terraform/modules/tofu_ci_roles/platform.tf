data "aws_iam_policy_document" "tofu_plan_platform_read" {
  statement {
    sid    = "ReadPlatformAwsResources"
    effect = "Allow"
    actions = [
      "acm:DescribeCertificate",
      "acm:GetCertificate",
      "acm:ListCertificates",
      "acm:ListTagsForCertificate",
      "cloudwatch:DescribeAlarms",
      "ec2:DescribeAccountAttributes",
      "ec2:DescribeAddresses",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeImages",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstanceCreditSpecifications",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstances",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSnapshots",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeVolumesModifications",
      "ec2:DescribeVpcAttribute",
      "ec2:DescribeVpcs",
      "ec2:GetEbsEncryptionByDefault",
      "elasticloadbalancing:DescribeListenerAttributes",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeLoadBalancerAttributes",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DescribeTags",
      "elasticloadbalancing:DescribeTargetGroupAttributes",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
      "iam:GetInstanceProfile",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfileTags",
      "iam:ListInstanceProfiles",
      "iam:ListInstanceProfilesForRole",
      "iam:ListPolicies",
      "iam:ListPolicyVersions",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "route53:GetHostedZone",
      "route53:ListHostedZones",
      "route53:ListResourceRecordSets",
      "secretsmanager:ListSecrets",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ReadPlatformBuckets"
    effect = "Allow"
    actions = [
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPolicyStatus",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
    ]
    resources = local.platform_s3_bucket_arns
  }

  statement {
    sid    = "ReadPlatformObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectTagging",
      "s3:GetObjectVersion",
      "s3:GetObjectVersionTagging",
    ]
    resources = local.platform_s3_object_arns
  }

  statement {
    sid    = "ReadPlatformSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:ListSecretVersionIds",
    ]
    resources = local.platform_secret_arns
  }

  statement {
    sid    = "ReadPlatformParameters"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameterHistory",
      "ssm:GetParameters",
    ]
    resources = local.platform_ssm_parameter_arns
  }
}

data "aws_iam_policy_document" "tofu_apply_platform_compute" {
  statement {
    sid    = "DescribePlatformEc2Resources"
    effect = "Allow"
    actions = [
      "ec2:DescribeAccountAttributes",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeImages",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstanceCreditSpecifications",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstances",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeSecurityGroupRules",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSnapshots",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeVolumesModifications",
      "ec2:DescribeVpcAttribute",
      "ec2:DescribeVpcs",
      "ec2:GetEbsEncryptionByDefault",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AllowPlatformEc2LaunchDependencies"
    effect    = "Allow"
    actions   = ["ec2:RunInstances"]
    resources = local.platform_ec2_launch_dependency_arns
  }

  statement {
    sid     = "AllowCreateSgInPlatformVpc"
    effect  = "Allow"
    actions = ["ec2:CreateSecurityGroup"]
    resources = [
      "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:vpc/*",
    ]
  }

  statement {
    sid       = "RunTaggedPlatformEc2Instances"
    effect    = "Allow"
    actions   = ["ec2:RunInstances"]
    resources = local.platform_ec2_created_resource_arns

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/managed-by"
      values   = ["tofu"]
    }
  }

  statement {
    sid    = "CreateTaggedPlatformEc2Resources"
    effect = "Allow"
    actions = [
      "ec2:CreateSecurityGroup",
      "ec2:CreateSnapshot",
      "ec2:CreateVolume",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/managed-by"
      values   = ["tofu"]
    }
  }

  statement {
    sid    = "ManageTaggedPlatformEc2Resources"
    effect = "Allow"
    actions = [
      "ec2:AttachVolume",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSnapshot",
      "ec2:DeleteTags",
      "ec2:DeleteVolume",
      "ec2:DetachVolume",
      "ec2:ModifySecurityGroupRules",
      "ec2:ModifyVolume",
      "ec2:RebootInstances",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:StartInstances",
      "ec2:StopInstances",
      "ec2:TerminateInstances",
      "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
      "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
    ]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/managed-by"
      values   = ["tofu"]
    }
  }

  statement {
    sid       = "TagPlatformEc2ResourcesOnCreate"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values = [
        "CreateSecurityGroup",
        "CreateSnapshot",
        "CreateVolume",
        "RunInstances",
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/managed-by"
      values   = ["tofu"]
    }
  }

  statement {
    sid       = "TagExistingPlatformEc2Resources"
    effect    = "Allow"
    actions   = ["ec2:CreateTags"]
    resources = ["*"]

    condition {
      test     = "StringEqualsIfExists"
      variable = "aws:RequestTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEqualsIfExists"
      variable = "aws:RequestTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEqualsIfExists"
      variable = "aws:RequestTag/managed-by"
      values   = ["tofu"]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/env"
      values   = [var.env_name]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/repo"
      values   = ["digibro-monorepo"]
    }

    condition {
      test     = "StringEquals"
      variable = "ec2:ResourceTag/managed-by"
      values   = ["tofu"]
    }
  }

  statement {
    sid    = "ManagePlatformLoadBalancing"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:CreateListener",
      "elasticloadbalancing:CreateLoadBalancer",
      "elasticloadbalancing:CreateRule",
      "elasticloadbalancing:CreateTargetGroup",
      "elasticloadbalancing:DeleteListener",
      "elasticloadbalancing:DeleteLoadBalancer",
      "elasticloadbalancing:DeleteRule",
      "elasticloadbalancing:DeleteTargetGroup",
      "elasticloadbalancing:DeregisterTargets",
      "elasticloadbalancing:DescribeListenerAttributes",
      "elasticloadbalancing:DescribeListeners",
      "elasticloadbalancing:DescribeLoadBalancerAttributes",
      "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeRules",
      "elasticloadbalancing:DescribeTags",
      "elasticloadbalancing:DescribeTargetGroupAttributes",
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
      "elasticloadbalancing:ModifyListener",
      "elasticloadbalancing:ModifyLoadBalancerAttributes",
      "elasticloadbalancing:ModifyRule",
      "elasticloadbalancing:ModifyTargetGroup",
      "elasticloadbalancing:ModifyTargetGroupAttributes",
      "elasticloadbalancing:RegisterTargets",
      "elasticloadbalancing:RemoveTags",
      "elasticloadbalancing:SetSecurityGroups",
      "elasticloadbalancing:SetSubnets",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "tofu_apply_platform_data" {
  statement {
    sid    = "ManagePlatformBuckets"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetEncryptionConfiguration",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
      "s3:GetBucketNotification",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPolicyStatus",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutEncryptionConfiguration",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutLifecycleConfiguration",
    ]
    resources = local.platform_s3_bucket_arns
  }

  statement {
    sid    = "ManagePlatformObjects"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = local.platform_s3_object_arns
  }

  statement {
    sid    = "ManagePlatformSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:CreateSecret",
      "secretsmanager:DeleteResourcePolicy",
      "secretsmanager:DeleteSecret",
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetResourcePolicy",
      "secretsmanager:GetSecretValue",
      "secretsmanager:PutResourcePolicy",
      "secretsmanager:PutSecretValue",
      "secretsmanager:RestoreSecret",
      "secretsmanager:TagResource",
      "secretsmanager:UntagResource",
      "secretsmanager:UpdateSecret",
    ]
    resources = local.platform_secret_arns
  }

  statement {
    sid    = "ManagePlatformParameters"
    effect = "Allow"
    actions = [
      "ssm:AddTagsToResource",
      "ssm:DeleteParameter",
      "ssm:DeleteParameters",
      "ssm:GetParameter",
      "ssm:GetParameterHistory",
      "ssm:GetParameters",
      "ssm:PutParameter",
      "ssm:RemoveTagsFromResource",
    ]
    resources = local.platform_ssm_parameter_arns
  }

  statement {
    sid    = "ManagePlatformLogsAndAlarms"
    effect = "Allow"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:PutMetricAlarm",
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DeleteRetentionPolicy",
      "logs:DescribeLogGroups",
      "logs:ListTagsForResource",
      "logs:PutRetentionPolicy",
      "logs:TagResource",
      "logs:UntagResource",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "tofu_apply_platform_acm" {
  statement {
    sid    = "ManagePlatformAcmCertificates"
    effect = "Allow"
    actions = [
      "acm:RequestCertificate",
      "acm:DeleteCertificate",
      "acm:DescribeCertificate",
      "acm:AddTagsToCertificate",
      "acm:ListTagsForCertificate",
      "acm:GetCertificate",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "tofu_apply_platform_iam" {
  statement {
    sid    = "ReadPlatformBoundaryPolicy"
    effect = "Allow"
    actions = [
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListPolicyVersions",
    ]
    resources = [local.platform_boundary_arn]
  }

  statement {
    sid       = "CreateBoundedPlatformRoles"
    effect    = "Allow"
    actions   = ["iam:CreateRole"]
    resources = local.platform_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.platform_boundary_arn]
    }
  }

  statement {
    sid    = "ManagePlatformRoles"
    effect = "Allow"
    actions = [
      "iam:DeleteRole",
      "iam:DeleteRolePermissionsBoundary",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]
    resources = local.platform_role_arns
  }

  statement {
    sid       = "SetPlatformRoleBoundary"
    effect    = "Allow"
    actions   = ["iam:PutRolePermissionsBoundary"]
    resources = local.platform_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.platform_boundary_arn]
    }
  }

  statement {
    sid       = "AttachApprovedPlatformManagedPolicies"
    effect    = "Allow"
    actions   = ["iam:AttachRolePolicy"]
    resources = local.platform_role_arns

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = local.approved_platform_managed_policy_arns
    }
  }

  statement {
    sid    = "ManagePlatformInstanceProfiles"
    effect = "Allow"
    actions = [
      "iam:AddRoleToInstanceProfile",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:GetInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
    ]
    resources = local.platform_instance_profile_arns
  }

  statement {
    sid       = "PassPlatformRolesToEc2"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = local.platform_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ec2.amazonaws.com"]
    }
  }
}
