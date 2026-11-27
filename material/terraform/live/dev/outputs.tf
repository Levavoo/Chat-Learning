output "ses_inbox_bucket_name" {
  description = "Name of the SES raw inbox bucket."
  value       = module.ses_inbound.inbox_bucket_name
}

output "ses_processor_lambda_arn" {
  description = "ARN of the SES inbox processor Lambda."
  value       = module.ses_inbound.processing_lambda_arn
}

output "review_cf_distribution_id" {
  description = "CloudFront distribution ID for the review environments."
  value       = module.review_frontend.distribution_id
}

output "review_cf_domain" {
  description = "CloudFront *.cloudfront.net domain for the review environments."
  value       = module.review_frontend.distribution_domain_name
}

output "review_assets_bucket" {
  description = "S3 bucket name holding review-frontend assets."
  value       = module.review_frontend.assets_bucket_name
}
