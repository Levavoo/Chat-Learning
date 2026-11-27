resource "aws_s3_bucket" "inbox" {
  bucket = local.name_prefix

  tags = merge(local.common_tags, {
    Name = local.name_prefix
  })

  lifecycle {
    precondition {
      condition     = local.account_id == var.account_id
      error_message = "Wrong account. Expected ${var.account_id}, got ${local.account_id}."
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  rule {
    id     = "expire-after-365-days"
    status = "Enabled"

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

resource "aws_s3_bucket_public_access_block" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "inbox" {
  bucket = aws_s3_bucket.inbox.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowSESPut"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.inbox.arn}/*"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = local.account_id
          }
          ArnLike = {
            "AWS:SourceArn" = "arn:aws:ses:${local.region}:${local.account_id}:receipt-rule-set/${aws_ses_receipt_rule_set.inbound.rule_set_name}:receipt-rule/*"
          }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.inbox.arn,
          "${aws_s3_bucket.inbox.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}

resource "aws_s3_bucket_policy" "staging" {
  bucket = aws_s3_bucket.staging.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.staging.arn,
          "${aws_s3_bucket.staging.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      },
    ]
  })
}

# Staging bucket: extracted files land here before moving into the ETL pipeline.
resource "aws_s3_bucket" "staging" {
  bucket = "${local.name_prefix}-staging"

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-staging"
  })
}

resource "aws_s3_bucket_public_access_block" "staging" {
  bucket = aws_s3_bucket.staging.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "staging" {
  bucket = aws_s3_bucket.staging.id

  versioning_configuration {
    status = "Enabled"
  }
}
