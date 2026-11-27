data "aws_caller_identity" "current" {}

locals {
  role_name            = "ki-lab-digibro-ci-deploy"
  role_arn             = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ki-lab-digibro-ci-deploy"
  oidc_provider_arn    = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/gitlab.kilab-platform.de"
  state_bucket_arn     = "arn:aws:s3:::${var.state_bucket_name}"
  state_bucket_objects = "arn:aws:s3:::${var.state_bucket_name}/*"
}

data "aws_iam_policy_document" "ci_deploy_assume" {
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

    # StringLike required because ref:* contains a wildcard.
    condition {
      test     = "StringLike"
      variable = "gitlab.kilab-platform.de:sub"
      values   = ["project_path:${var.gitlab_project_path}:ref_type:branch:ref:*"]
    }
  }
}

data "aws_iam_policy_document" "ci_deploy_oidc" {
  statement {
    sid    = "ManageOidcProvider"
    effect = "Allow"
    actions = [
      "iam:CreateOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
    ]
    resources = [local.oidc_provider_arn]
  }

  # iam:ListOpenIDConnectProviders is account-level and cannot be scoped to a resource ARN.
  statement {
    sid       = "ListOidcProviders"
    effect    = "Allow"
    actions   = ["iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  # Tofu reads the role and its inline policies during plan to detect drift.
  statement {
    sid    = "ReadSelfRole"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
    ]
    resources = [local.role_arn]
  }
}

data "aws_iam_policy_document" "ci_deploy_s3" {
  statement {
    sid    = "StateBucketAccess"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
      "s3:GetBucketVersioning",
    ]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid    = "StateBucketObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = [local.state_bucket_objects]
  }
}

data "aws_iam_policy_document" "ci_deploy_ecr" {
  # ecr:GetAuthorizationToken is account-level; cannot be scoped to a repository ARN.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrRepositoryAccess"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository",
      "ecr:DeleteRepository",
      "ecr:DescribeRepositories",
      "ecr:ListTagsForResource",
      "ecr:TagResource",
      "ecr:UntagResource",
      "ecr:PutLifecyclePolicy",
      "ecr:GetLifecyclePolicy",
      "ecr:DeleteLifecyclePolicy",
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "ci_deploy" {
  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.ci_deploy_assume.json

  tags = merge(
    {
      Name      = local.role_name
      component = "ci-deploy"
    },
    var.additional_tags,
  )

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${data.aws_caller_identity.current.account_id}."
    }
  }
}

resource "aws_iam_role_policy" "ci_deploy_oidc" {
  name   = "oidc-provider-manage"
  role   = aws_iam_role.ci_deploy.name
  policy = data.aws_iam_policy_document.ci_deploy_oidc.json
}

resource "aws_iam_role_policy" "ci_deploy_s3" {
  name   = "state-bucket-access"
  role   = aws_iam_role.ci_deploy.name
  policy = data.aws_iam_policy_document.ci_deploy_s3.json
}

resource "aws_iam_role_policy" "ci_deploy_ecr" {
  name   = "ecr-access"
  role   = aws_iam_role.ci_deploy.name
  policy = data.aws_iam_policy_document.ci_deploy_ecr.json
}
