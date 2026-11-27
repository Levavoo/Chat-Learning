variable "account_id" {
  description = "AWS account ID where the OpenTofu CI roles are created. Verified by precondition at plan time."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id must be a 12-digit AWS account ID."
  }
}

variable "env_name" {
  description = "Environment name used in role names and tags, for example dev or prod."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,31}$", var.env_name))
    error_message = "env_name must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "gitlab_project_path" {
  description = "GitLab project path used in the OIDC trust policy sub claim. Format: <namespace>/<project>."
  type        = string
  default     = "renate/digibro-monorepo"
}

variable "default_branch" {
  description = "Default branch allowed to assume apply roles."
  type        = string
  default     = "main"

  validation {
    condition     = length(trimspace(var.default_branch)) > 0 && !can(regex("\\s", var.default_branch))
    error_message = "default_branch must be non-empty and must not contain whitespace."
  }
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket used for OpenTofu remote state in this account."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.state_bucket_name))
    error_message = "state_bucket_name must be a valid S3 bucket name."
  }
}

variable "state_key" {
  description = "S3 object key for the OpenTofu state file in this account."
  type        = string

  validation {
    condition     = length(trimspace(var.state_key)) > 0 && !startswith(var.state_key, "/") && !endswith(var.state_key, "/")
    error_message = "state_key must be non-empty and must not start or end with a slash."
  }
}

variable "allow_apply_role_self_management" {
  # WARNING: true lets the apply role modify its own trust/inline policies — privilege escalation path.
  description = "Allow the apply role to manage its own IAM role and inline policies. Keep false for normal CI; enable only when applying with operator/bootstrap credentials."
  type        = bool
  default     = false
}

variable "enable_platform_permissions" {
  description = "Allow the OpenTofu CI roles to plan and apply bounded platform infrastructure for this environment."
  type        = bool
  default     = false
}

variable "platform_region" {
  description = "AWS region where platform workload resources are deployed. Defaults to the provider region when unset."
  type        = string
  default     = null

  validation {
    condition     = var.platform_region == null || can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", coalesce(var.platform_region, "")))
    error_message = "platform_region must be a valid AWS region name, for example eu-central-1."
  }
}

variable "enable_packer_ami_role" {
  description = "Create the IAM role for Packer AMI builds in this environment."
  type        = bool
  default     = false
}

variable "additional_tags" {
  description = "Extra tags merged into the resource tag set."
  type        = map(string)
  default     = {}
}
