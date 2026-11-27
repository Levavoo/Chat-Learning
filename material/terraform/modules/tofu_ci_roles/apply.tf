data "aws_iam_policy_document" "tofu_apply_manage_root" {
  source_policy_documents = [data.aws_iam_policy_document.tofu_plan_provider_read.json]

  statement {
    sid    = "ManageOidcProvider"
    effect = "Allow"
    actions = [
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = [local.oidc_provider_arn]
  }

  statement {
    sid    = "ManageManagedRoles"
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = local.managed_role_arns
  }

  # ecr:CreateRepository is bootstrap-only; scoped to this repo ARN to prevent creating others.
  statement {
    sid    = "CreateEcrRepository"
    effect = "Allow"
    actions = [
      "ecr:CreateRepository",
      "ecr:DescribeRepositories",
    ]
    resources = [local.ecr_repository_arn]
  }

  statement {
    sid    = "ManageEcrRepository"
    effect = "Allow"
    actions = [
      "ecr:DeleteLifecyclePolicy",
      "ecr:DeleteRepository",
      "ecr:DeleteRepositoryPolicy",
      "ecr:GetLifecyclePolicy",
      "ecr:GetRepositoryPolicy",
      "ecr:ListTagsForResource",
      "ecr:PutImageScanningConfiguration",
      "ecr:PutImageTagMutability",
      "ecr:PutLifecyclePolicy",
      "ecr:SetRepositoryPolicy",
      "ecr:TagResource",
      "ecr:UntagResource",
    ]
    resources = [local.ecr_repository_arn]
  }

}

data "aws_iam_policy_document" "tofu_apply_guardrails" {
  statement {
    sid    = "DenyApplyRoleSelfMutation"
    effect = "Deny"
    actions = [
      "iam:AttachRolePolicy",
      "iam:DeleteRole",
      "iam:DeleteRolePermissionsBoundary",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePermissionsBoundary",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]
    resources = [local.apply_role_arn]
  }
}
