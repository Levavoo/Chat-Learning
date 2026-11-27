resource "aws_iam_role" "tofu_plan" {
  name               = local.plan_role_name
  assume_role_policy = data.aws_iam_policy_document.tofu_plan_assume.json

  tags = merge(
    {
      Name = local.plan_role_name
      type = "plan"
    },
    local.role_tags,
  )

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${data.aws_caller_identity.current.account_id}."
    }
  }
}

resource "aws_iam_role" "tofu_apply" {
  name               = local.apply_role_name
  assume_role_policy = data.aws_iam_policy_document.tofu_apply_assume.json

  tags = merge(
    {
      Name = local.apply_role_name
      type = "apply"
    },
    local.role_tags,
  )

  lifecycle {
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${data.aws_caller_identity.current.account_id}."
    }
  }
}

resource "aws_iam_role_policy" "tofu_plan_state_read" {
  name   = "state-read"
  role   = aws_iam_role.tofu_plan.name
  policy = data.aws_iam_policy_document.tofu_plan_state_read.json
}

resource "aws_iam_role_policy" "tofu_plan_provider_read" {
  name   = "provider-read"
  role   = aws_iam_role.tofu_plan.name
  policy = data.aws_iam_policy_document.tofu_plan_provider_read.json
}

resource "aws_iam_role_policy" "tofu_apply_state_write" {
  name   = "state-write"
  role   = aws_iam_role.tofu_apply.name
  policy = data.aws_iam_policy_document.tofu_apply_state_write.json
}

resource "aws_iam_role_policy" "tofu_apply_manage_root" {
  name   = "manage-root"
  role   = aws_iam_role.tofu_apply.name
  policy = data.aws_iam_policy_document.tofu_apply_manage_root.json
}

resource "aws_iam_role_policy" "tofu_apply_guardrails" {
  count = var.allow_apply_role_self_management ? 0 : 1

  name   = "guardrails"
  role   = aws_iam_role.tofu_apply.name
  policy = data.aws_iam_policy_document.tofu_apply_guardrails.json
}

resource "aws_iam_policy" "platform_permissions_boundary" {
  count = var.enable_platform_permissions ? 1 : 0

  name        = local.platform_boundary_name
  description = "Maximum permissions for ${var.env_name} platform workload roles created by OpenTofu CI."
  policy      = data.aws_iam_policy_document.platform_permissions_boundary.json

  tags = merge(
    {
      Name      = local.platform_boundary_name
      component = "platform-ci"
      type      = "permissions-boundary"
    },
    local.role_tags,
  )
}

resource "aws_iam_role_policy" "tofu_plan_platform_read" {
  count = var.enable_platform_permissions ? 1 : 0

  name   = "platform-read"
  role   = aws_iam_role.tofu_plan.name
  policy = data.aws_iam_policy_document.tofu_plan_platform_read.json
}

resource "aws_iam_policy" "tofu_apply_platform_compute" {
  count = var.enable_platform_permissions ? 1 : 0

  name        = local.apply_platform_compute_policy_name
  description = "Platform compute permissions for ${var.env_name} OpenTofu apply."
  policy      = data.aws_iam_policy_document.tofu_apply_platform_compute.json

  tags = merge(
    {
      Name      = local.apply_platform_compute_policy_name
      component = "tofu-ci"
      type      = "platform-compute"
    },
    local.role_tags,
  )
}

resource "aws_iam_role_policy_attachment" "tofu_apply_platform_compute" {
  count = var.enable_platform_permissions ? 1 : 0

  role       = aws_iam_role.tofu_apply.name
  policy_arn = aws_iam_policy.tofu_apply_platform_compute[count.index].arn
}

resource "aws_iam_policy" "tofu_apply_platform_data" {
  count = var.enable_platform_permissions ? 1 : 0

  name        = local.apply_platform_data_policy_name
  description = "Platform data permissions for ${var.env_name} OpenTofu apply."
  policy      = data.aws_iam_policy_document.tofu_apply_platform_data.json

  tags = merge(
    {
      Name      = local.apply_platform_data_policy_name
      component = "tofu-ci"
      type      = "platform-data"
    },
    local.role_tags,
  )
}

resource "aws_iam_role_policy_attachment" "tofu_apply_platform_data" {
  count = var.enable_platform_permissions ? 1 : 0

  role       = aws_iam_role.tofu_apply.name
  policy_arn = aws_iam_policy.tofu_apply_platform_data[count.index].arn
}

resource "aws_iam_policy" "tofu_apply_platform_iam" {
  count = var.enable_platform_permissions ? 1 : 0

  name        = local.apply_platform_iam_policy_name
  description = "Platform IAM permissions for ${var.env_name} OpenTofu apply."
  policy      = data.aws_iam_policy_document.tofu_apply_platform_iam.json

  tags = merge(
    {
      Name      = local.apply_platform_iam_policy_name
      component = "tofu-ci"
      type      = "platform-iam"
    },
    local.role_tags,
  )
}

resource "aws_iam_role_policy_attachment" "tofu_apply_platform_iam" {
  count = var.enable_platform_permissions ? 1 : 0

  role       = aws_iam_role.tofu_apply.name
  policy_arn = aws_iam_policy.tofu_apply_platform_iam[count.index].arn
}

resource "aws_iam_policy" "tofu_apply_platform_acm" {
  count = var.enable_platform_permissions ? 1 : 0

  name        = local.apply_platform_acm_policy_name
  description = "Platform ACM permissions for ${var.env_name} OpenTofu apply."
  policy      = data.aws_iam_policy_document.tofu_apply_platform_acm.json

  tags = merge(
    {
      Name      = local.apply_platform_acm_policy_name
      component = "tofu-ci"
      type      = "platform-acm"
    },
    local.role_tags,
  )
}

resource "aws_iam_role_policy_attachment" "tofu_apply_platform_acm" {
  count = var.enable_platform_permissions ? 1 : 0

  role       = aws_iam_role.tofu_apply.name
  policy_arn = aws_iam_policy.tofu_apply_platform_acm[count.index].arn
}