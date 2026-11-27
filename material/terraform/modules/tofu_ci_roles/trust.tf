data "aws_iam_policy_document" "tofu_plan_assume" {
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

data "aws_iam_policy_document" "tofu_apply_assume" {
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
      test     = "StringEquals"
      variable = "gitlab.kilab-platform.de:sub"
      values   = ["project_path:${var.gitlab_project_path}:ref_type:branch:ref:${var.default_branch}"]
    }
  }
}