output "provider_arn" {
  description = "ARN of the GitLab CI OIDC provider."
  value       = aws_iam_openid_connect_provider.gitlab_ci.arn
}
