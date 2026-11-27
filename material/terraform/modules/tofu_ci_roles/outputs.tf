output "plan_role_arn" {
  description = "ARN of the OpenTofu CI plan role."
  value       = aws_iam_role.tofu_plan.arn
}

output "apply_role_arn" {
  description = "ARN of the OpenTofu CI apply role."
  value       = aws_iam_role.tofu_apply.arn
}

output "state_bucket_name" {
  description = "Name of the S3 bucket used for OpenTofu remote state."
  value       = var.state_bucket_name
}

output "state_key" {
  description = "S3 object key for the OpenTofu state file."
  value       = var.state_key
}

output "packer_ami_role_arn" {
  description = "ARN of the Packer AMI CI role. Empty string when disabled."
  value       = var.enable_packer_ami_role ? aws_iam_role.packer_ami[0].arn : ""
}
