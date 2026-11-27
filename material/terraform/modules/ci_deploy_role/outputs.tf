output "role_arn" {
  description = "ARN of the CI deploy role. Store as DIGIBRO_DEV_DEPLOY_ROLE_ARN or DIGIBRO_PROD_DEPLOY_ROLE_ARN in GitLab CI project variables."
  value       = aws_iam_role.ci_deploy.arn
}

output "role_name" {
  description = "Name of the CI deploy role."
  value       = aws_iam_role.ci_deploy.name
}
