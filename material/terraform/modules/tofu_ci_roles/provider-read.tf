data "aws_iam_policy_document" "tofu_plan_provider_read" {
  statement {
    sid    = "ReadOidcProvider"
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviderTags",
    ]
    resources = [local.oidc_provider_arn]
  }

  statement {
    sid       = "ListOidcProviders"
    effect    = "Allow"
    actions   = ["iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  statement {
    sid    = "ReadManagedRoles"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = local.readable_role_arns
  }

  statement {
    sid       = "DescribeEcrRepositories"
    effect    = "Allow"
    actions   = ["ecr:DescribeRepositories"]
    resources = [local.ecr_repository_arn]
  }

  statement {
    sid    = "ReadEcrRepository"
    effect = "Allow"
    actions = [
      "ecr:GetLifecyclePolicy",
      "ecr:ListTagsForResource",
    ]
    resources = [local.ecr_repository_arn]
  }
}