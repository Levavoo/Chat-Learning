data "archive_file" "processor" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/.build/processor.zip"
  excludes    = ["__pycache__", "tests", "*.pyc"]
}

resource "aws_lambda_function" "processor" {
  function_name    = "${local.name_prefix}-processor"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 256
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256

  environment {
    variables = {
      ALLOWED_SENDERS     = local.allowed_senders_csv
      STAGING_BUCKET      = aws_s3_bucket.staging.id
      INBOX_BUCKET        = aws_s3_bucket.inbox.id
      SNS_ALERT_TOPIC_ARN = aws_sns_topic.alerts.arn
      REPLY_FROM_ADDRESS  = var.recipient_address
    }
  }

  tracing_config {
    mode = "Active"
  }

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-processor" })
}

resource "aws_lambda_permission" "ses_invoke" {
  statement_id   = "AllowSESInvoke"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.processor.function_name
  principal      = "ses.amazonaws.com"
  source_account = local.account_id
  source_arn     = "arn:aws:ses:${local.region}:${local.account_id}:receipt-rule-set/${aws_ses_receipt_rule_set.inbound.rule_set_name}:receipt-rule/${local.receipt_rule_name}"
}

resource "aws_lambda_function_event_invoke_config" "processor" {
  function_name          = aws_lambda_function.processor.function_name
  maximum_retry_attempts = 2

  destination_config {
    on_failure {
      destination = aws_sns_topic.alerts.arn
    }
  }
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.name_prefix}-processor"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name_prefix}-processor-errors"
  alarm_description   = "SES inbox processor Lambda errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.processor.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  tags = local.common_tags
}
