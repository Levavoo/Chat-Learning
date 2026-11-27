# Trust: any branch in the project — the CI manual gate is the access control.
data "aws_iam_policy_document" "packer_ami_assume" {
  count = var.enable_packer_ami_role ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "gitlab.kilab-platform.de:aud"
      values   = ["https://gitlab.kilab-platform.de"]
    }

    condition {
      test     = "StringLike"
      variable = "gitlab.kilab-platform.de:sub"
      values   = ["project_path:${var.gitlab_project_path}:ref_type:branch:ref:*"]
    }
  }
}

resource "aws_iam_role" "packer_ami" {
  count              = var.enable_packer_ami_role ? 1 : 0
  name               = "digibro-${var.env_name}-packer-ami"
  assume_role_policy = data.aws_iam_policy_document.packer_ami_assume[0].json
  tags               = merge(local.role_tags, { Name = "digibro-${var.env_name}-packer-ami" })

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${data.aws_caller_identity.current.account_id}."
    }
  }
}

data "aws_iam_policy_document" "packer_ami" {
  count = var.enable_packer_ami_role ? 1 : 0

  statement {
    sid    = "PackerDescribe"
    effect = "Allow"
    actions = [
      "ec2:DescribeImages",
      "ec2:DescribeImageAttribute",
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceAttribute",
      "ec2:DescribeInstanceStatus",
      "ec2:DescribeInstanceTypeOfferings",
      "ec2:DescribeRegions",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeVpcs",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerBuilderLifecycle"
    effect = "Allow"
    actions = [
      "ec2:RunInstances",
      "ec2:StopInstances",
      "ec2:TerminateInstances",
      "ec2:GetPasswordData",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerAmi"
    effect = "Allow"
    actions = [
      "ec2:CreateImage",
      "ec2:RegisterImage",
      "ec2:DeregisterImage",
      "ec2:ModifyImageAttribute",
      "ec2:CopyImage",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerSnapshot"
    effect = "Allow"
    actions = [
      "ec2:CreateSnapshot",
      "ec2:DeleteSnapshot",
      "ec2:ModifySnapshotAttribute",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerVolume"
    effect = "Allow"
    actions = [
      "ec2:AttachVolume",
      "ec2:CreateVolume",
      "ec2:DeleteVolume",
      "ec2:DetachVolume",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerKeyPair"
    effect = "Allow"
    actions = [
      "ec2:CreateKeyPair",
      "ec2:DeleteKeyPair",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerSecurityGroup"
    effect = "Allow"
    actions = [
      "ec2:CreateSecurityGroup",
      "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupIngress",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PackerTags"
    effect = "Allow"
    actions = [
      "ec2:CreateTags",
      "ec2:DeleteTags",
    ]
    resources = ["*"]
  }

  statement {
    sid     = "PackerSsmOutput"
    effect  = "Allow"
    actions = ["ssm:PutParameter"]
    resources = [
      "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.env_name}/renate/langfuse-ami-id",
      "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.env_name}/renate/runner-worker-ami-id",
      "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.env_name}/renate/runner-manager-ami-id",
    ]
  }
}

resource "aws_iam_role_policy" "packer_ami" {
  count  = var.enable_packer_ami_role ? 1 : 0
  name   = "packer-ami"
  role   = aws_iam_role.packer_ami[0].name
  policy = data.aws_iam_policy_document.packer_ami[0].json
}
