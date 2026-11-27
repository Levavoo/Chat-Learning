variable "account_id" {
  description = "AWS account ID where the role is being created. Verified by precondition at plan time."
  type        = string
}

variable "gitlab_project_path" {
  description = "GitLab project path used in the OIDC trust policy sub claim. Format: <namespace>/<project>. The sub claim becomes: project_path:<value>:ref_type:branch:ref:*."
  type        = string
  default     = "renate/digibro-monorepo"
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket used for OpenTofu remote state in this account. Scoped in the S3 permission statements."
  type        = string
}

variable "additional_tags" {
  description = "Extra tags merged into the resource tag set."
  type        = map(string)
  default     = {}
}
