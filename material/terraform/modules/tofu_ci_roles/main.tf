data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  plan_role_name       = "ki-lab-digibro-tofu-plan-${var.env_name}"
  apply_role_name      = "ki-lab-digibro-tofu-apply-${var.env_name}"
  ci_deploy_role_name  = "ki-lab-digibro-ci-deploy"
  ecr_repository_name  = "renate-lambda"
  platform_name_prefix = "ki-lab-digibro-${var.env_name}"
  platform_region      = coalesce(var.platform_region, data.aws_region.current.id)

  oidc_provider_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/gitlab.kilab-platform.de"

  plan_role_arn                      = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.plan_role_name}"
  apply_role_arn                     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.apply_role_name}"
  ci_deploy_role_arn                 = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.ci_deploy_role_name}"
  platform_boundary_name             = "${local.platform_name_prefix}-permissions-boundary"
  platform_boundary_arn              = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/${local.platform_boundary_name}"
  apply_platform_compute_policy_name = "${local.apply_role_name}-platform-compute"
  apply_platform_data_policy_name    = "${local.apply_role_name}-platform-data"
  apply_platform_iam_policy_name     = "${local.apply_role_name}-platform-iam"
  apply_platform_acm_policy_name     = "${local.apply_role_name}-platform-acm"
  platform_role_arns = [
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.platform_name_prefix}-*",
  ]
  platform_instance_profile_arns = [
    "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/${local.platform_name_prefix}-*",
  ]
  platform_ec2_launch_dependency_arns = [
    "arn:aws:ec2:${local.platform_region}::image/*",
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:key-pair/*",
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:network-interface/*",
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:security-group/*",
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:subnet/*",
  ]
  platform_ec2_created_resource_arns = [
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:instance/*",
    "arn:aws:ec2:${local.platform_region}:${data.aws_caller_identity.current.account_id}:volume/*",
  ]
  platform_s3_bucket_arns = [
    "arn:aws:s3:::ki-lab-digibro-${var.env_name}-platform-*",
    "arn:aws:s3:::digibro-langfuse-${var.env_name}-*",
  ]
  platform_s3_object_arns = [
    for bucket_arn in local.platform_s3_bucket_arns : "${bucket_arn}/*"
  ]
  platform_secret_arns = [
    "arn:aws:secretsmanager:${local.platform_region}:${data.aws_caller_identity.current.account_id}:secret:${local.platform_name_prefix}-*",
    "arn:aws:secretsmanager:${local.platform_region}:${data.aws_caller_identity.current.account_id}:secret:digibro/${var.env_name}/*",
    "arn:aws:secretsmanager:${local.platform_region}:${data.aws_caller_identity.current.account_id}:secret:langfuse/${var.env_name}/*",
  ]
  platform_ssm_parameter_arns = [
    "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.env_name}/renate/*",
    "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.env_name}/langfuse/*",
    "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/digibro/${var.env_name}/*",
    "arn:aws:ssm:${local.platform_region}:${data.aws_caller_identity.current.account_id}:parameter/langfuse/${var.env_name}/*",
  ]
  approved_platform_managed_policy_arns = [
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
  ]

  readable_role_arns = [
    local.ci_deploy_role_arn,
    local.plan_role_arn,
    local.apply_role_arn,
  ]
  managed_role_arns = concat(
    [
      local.ci_deploy_role_arn,
      local.plan_role_arn,
    ],
    var.allow_apply_role_self_management ? [local.apply_role_arn] : [],
  )

  state_bucket_arn = "arn:aws:s3:::${var.state_bucket_name}"
  state_object_arns = [
    "arn:aws:s3:::${var.state_bucket_name}/${var.state_key}",
    "arn:aws:s3:::${var.state_bucket_name}/${var.state_key}.tflock",
  ]

  ecr_repository_arn = "arn:aws:ecr:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:repository/${local.ecr_repository_name}"

  role_tags = merge(
    {
      component = "tofu-ci"
    },
    var.additional_tags,
  )
}
