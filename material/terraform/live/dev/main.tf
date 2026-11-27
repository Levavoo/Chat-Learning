# Langfuse DEV was moved to renate/langfuse; release from state without destroying.
removed {
  from = module.langfuse
  lifecycle {
    destroy = false
  }
}

module "ses_inbound" {
  source     = "../../modules/ses_inbound"
  env_name   = "dev"
  account_id = "831926590742"

  hosted_zone_id    = "Z05955572KK17DXDISFXL"
  domain_name       = "mail.digibro-team.de"
  recipient_address = "brochures@mail.digibro-team.de"

  allowed_senders = ["renate@drv-bund.de"]

  # No other SES receipt rule set in this account.
  manage_active_rule_set = true

  alert_emails = [
    "renate@drv-bund.de",
    "ki-reha-anwendungsbetrieb@drv-bund.de",
  ]

  providers = {
    aws = aws.platform
  }
}

module "review_frontend" {
  source = "git::https://gitlab.kilab-platform.de/renate/tofu-modules.git//modules/review-frontend?ref=review-frontend-0.1.2"

  env_name   = "dev"
  account_id = "831926590742"

  providers = {
    aws = aws.platform
  }
}
