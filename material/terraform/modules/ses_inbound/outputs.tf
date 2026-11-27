output "inbox_bucket_arn" {
  description = "ARN of the raw inbox S3 bucket."
  value       = aws_s3_bucket.inbox.arn
}

output "inbox_bucket_name" {
  description = "Name of the raw inbox S3 bucket."
  value       = aws_s3_bucket.inbox.id
}

output "staging_bucket_arn" {
  description = "ARN of the staging S3 bucket (pre-processing)."
  value       = aws_s3_bucket.staging.arn
}

output "staging_bucket_name" {
  description = "Name of the staging S3 bucket (pre-processing)."
  value       = aws_s3_bucket.staging.id
}

output "processing_lambda_arn" {
  description = "ARN of the email processing Lambda function."
  value       = aws_lambda_function.processor.arn
}

output "processing_lambda_function_name" {
  description = "Name of the email processing Lambda function."
  value       = aws_lambda_function.processor.function_name
}

output "sns_topic_arn" {
  description = "ARN of the alerting SNS topic."
  value       = aws_sns_topic.alerts.arn
}
