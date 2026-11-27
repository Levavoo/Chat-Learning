resource "aws_ses_domain_identity" "inbound" {
  domain = var.domain_name
}

resource "aws_ses_domain_dkim" "inbound" {
  domain = aws_ses_domain_identity.inbound.domain
}

resource "aws_route53_record" "ses_verification" {
  zone_id = var.hosted_zone_id
  name    = "_amazonses.${var.domain_name}"
  type    = "TXT"
  ttl     = 600
  records = [aws_ses_domain_identity.inbound.verification_token]
}

resource "aws_route53_record" "ses_dkim" {
  count = 3

  zone_id = var.hosted_zone_id
  name    = "${aws_ses_domain_dkim.inbound.dkim_tokens[count.index]}._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 600
  records = ["${aws_ses_domain_dkim.inbound.dkim_tokens[count.index]}.dkim.amazonses.com"]
}

resource "aws_route53_record" "mx" {
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "MX"
  ttl     = 300
  records = ["10 inbound-smtp.${local.region}.amazonaws.com"]
}

resource "aws_ses_domain_identity_verification" "inbound" {
  domain = aws_ses_domain_identity.inbound.id

  depends_on = [aws_route53_record.ses_verification]
}

resource "aws_ses_receipt_rule_set" "inbound" {
  rule_set_name = "renate-brochure-inbound-${var.env_name}"
}

# WARNING: SES allows exactly ONE active receipt rule set per account/region;
# activating this one deactivates whatever is currently active. Gated by
# `manage_active_rule_set` so a first apply cannot silently break an existing set.
resource "aws_ses_active_receipt_rule_set" "inbound" {
  count = var.manage_active_rule_set ? 1 : 0

  rule_set_name = aws_ses_receipt_rule_set.inbound.rule_set_name
}

resource "aws_ses_receipt_rule" "brochures" {
  name          = local.receipt_rule_name
  rule_set_name = aws_ses_receipt_rule_set.inbound.rule_set_name
  recipients    = [var.recipient_address]
  enabled       = true
  scan_enabled  = true

  s3_action {
    bucket_name       = aws_s3_bucket.inbox.id
    object_key_prefix = "raw/"
    position          = 1
  }

  lambda_action {
    function_arn    = aws_lambda_function.processor.arn
    invocation_type = "Event"
    position        = 2
  }

  depends_on = [
    aws_ses_domain_identity_verification.inbound,
    aws_s3_bucket_policy.inbox,
    aws_lambda_permission.ses_invoke,
  ]
}
