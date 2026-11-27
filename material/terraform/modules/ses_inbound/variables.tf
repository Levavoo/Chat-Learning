variable "env_name" {
  description = "Environment name. Only dev is supported today (bootstrap IAM prerequisites are dev-only)."
  type        = string

  validation {
    condition     = contains(["dev"], var.env_name)
    error_message = "env_name must be dev. Other environments require bootstrap IAM changes first (see module README)."
  }
}

variable "manage_active_rule_set" {
  description = "Activate the created receipt rule set. SES allows exactly ONE active rule set per account/region; enabling this deactivates any other active set."
  type        = bool
  default     = false
}

variable "account_id" {
  description = "AWS account ID. Verified by precondition at plan time."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "hosted_zone_id" {
  description = "Route53 hosted zone ID for the parent domain."
  type        = string
}

variable "domain_name" {
  description = "Subdomain for SES inbound receiving (e.g. mail.digibro-team.de)."
  type        = string
}

variable "recipient_address" {
  description = "Email address to receive brochure updates (e.g. brochures@mail.digibro-team.de)."
  type        = string
}

variable "allowed_senders" {
  description = "List of email addresses allowed to send to this inbox. Others are quarantined."
  type        = list(string)
}

variable "alert_emails" {
  description = "Official mailboxes for SES brochure-workflow SNS alerts. Must not include individual subscriptions."
  type        = list(string)

  validation {
    condition = (
      length(var.alert_emails) == 2 &&
      length(toset(var.alert_emails)) == 2 &&
      alltrue([
        for email in var.alert_emails : contains([
          "renate@drv-bund.de",
          "ki-reha-anwendungsbetrieb@drv-bund.de",
        ], email)
      ])
    )
    error_message = "alert_emails must contain exactly the two official mailboxes."
  }
}

variable "additional_tags" {
  description = "Extra tags merged into all resources."
  type        = map(string)
  default     = {}
}
