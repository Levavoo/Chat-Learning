# Permissions boundary: max permissions for platform workload roles.
data "aws_iam_policy_document" "platform_permissions_boundary" {
  statement {
    sid    = "AllowSsmManagedInstanceCore"
    effect = "Allow"
    actions = [
      "ec2messages:AcknowledgeMessage",
      "ec2messages:DeleteMessage",
      "ec2messages:FailMessage",
      "ec2messages:GetEndpoint",
      "ec2messages:GetMessages",
      "ec2messages:SendReply",
      "ssm:DescribeAssociation",
      "ssm:GetDeployablePatchSnapshotForInstance",
      "ssm:GetDocument",
      "ssm:GetManifest",
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:ListAssociations",
      "ssm:ListInstanceAssociations",
      "ssm:PutComplianceItems",
      "ssm:PutConfigurePackageResult",
      "ssm:PutInventory",
      "ssm:UpdateAssociationStatus",
      "ssm:UpdateInstanceAssociationStatus",
      "ssm:UpdateInstanceInformation",
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowPlatformSecretRead"
    effect = "Allow"
    actions = [
      "secretsmanager:DescribeSecret",
      "secretsmanager:GetSecretValue",
    ]
    resources = local.platform_secret_arns
  }

  statement {
    sid    = "AllowPlatformObjectStorage"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]
    resources = local.platform_s3_bucket_arns
  }

  statement {
    sid    = "AllowPlatformObjectAccess"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = local.platform_s3_object_arns
  }

  statement {
    sid    = "AllowPlatformLogs"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}