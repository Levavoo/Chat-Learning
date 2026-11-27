data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name_prefix         = "ki-lab-digibro-${var.env_name}-platform-ses-inbox"
  receipt_rule_name   = "brochures-${var.env_name}"
  region              = data.aws_region.current.region
  account_id          = data.aws_caller_identity.current.account_id
  allowed_senders_csv = join(",", var.allowed_senders)

  common_tags = merge(
    {
      project      = "renate"
      component    = "ses-inbound"
      env          = var.env_name
      repo         = "digibro-monorepo"
      "managed-by" = "tofu"
    },
    var.additional_tags,
  )
}
