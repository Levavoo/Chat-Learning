resource "aws_iam_role" "lambda" {
  name = "${local.name_prefix}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
    ]
  })

  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/ki-lab-digibro-${var.env_name}-permissions-boundary"

  tags = merge(local.common_tags, { Name = "${local.name_prefix}-lambda" })
}

resource "aws_iam_role_policy" "lambda" {
  name = "ses-inbox-processor"
  role = aws_iam_role.lambda.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadInboxBucket"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.inbox.arn}/*"
      },
      {
        Sid      = "WriteStagingBucket"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:PutObjectTagging"]
        Resource = "${aws_s3_bucket.staging.arn}/*"
      },
      {
        Sid      = "PublishAlerts"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.processor.arn}:*"
      },
      {
        Sid    = "XRayTracing"
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
        ]
        Resource = "*"
      },
      {
        Sid    = "SendReplyEmail"
        Effect = "Allow"
        Action = ["ses:SendEmail"]
        Resource = concat(
          ["arn:aws:ses:${local.region}:${local.account_id}:identity/${var.domain_name}"],
          [for s in var.allowed_senders : "arn:aws:ses:${local.region}:${local.account_id}:identity/${s}"],
        )
      },
    ]
  })
}
