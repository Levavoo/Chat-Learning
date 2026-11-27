variable "account_id" {
  description = "AWS account ID where the OIDC provider is being created. Used in the precondition to guard against applying in the wrong account."
  type        = string
}

variable "thumbprint" {
  description = "SHA1 fingerprint of the GitLab instance TLS cert root CA. Recompute on cert rotation -- see docs/reference/aws_accounts.md."
  type        = string
  default     = "a8430fcd6cb0352705910d35b15ebcba9dba992b"
}

variable "additional_tags" {
  description = "Extra tags merged into the resource tag set."
  type        = map(string)
  default     = {}
}
