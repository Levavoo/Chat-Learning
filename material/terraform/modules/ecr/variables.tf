variable "account_id" {
  description = "AWS account ID where the ECR repository is being created. Used in the precondition to guard against applying in the wrong account."
  type        = string
}

variable "additional_tags" {
  description = "Extra tags merged into the resource tag set."
  type        = map(string)
  default     = {}
}
