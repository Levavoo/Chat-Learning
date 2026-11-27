data "aws_iam_policy_document" "tofu_plan_state_read" {
  statement {
    sid    = "StateBucketMetadataRead"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
    ]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid    = "StateLock"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = local.state_object_arns
  }

  statement {
    sid       = "StateBucketListStateObjects"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        var.state_key,
        "${var.state_key}.tflock",
      ]
    }
  }

  statement {
    sid       = "StateObjectRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = local.state_object_arns
  }
}

data "aws_iam_policy_document" "tofu_apply_state_write" {
  source_policy_documents = [data.aws_iam_policy_document.tofu_plan_state_read.json]

  statement {
    sid    = "StateObjectWrite"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = local.state_object_arns
  }
}
