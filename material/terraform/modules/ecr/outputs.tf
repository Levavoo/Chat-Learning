output "repository_url" {
  description = "ECR repository URL for use in buildah push and Lambda image URIs."
  value       = aws_ecr_repository.renate_lambda.repository_url
}

output "repository_arn" {
  description = "ARN of the ECR repository."
  value       = aws_ecr_repository.renate_lambda.arn
}
