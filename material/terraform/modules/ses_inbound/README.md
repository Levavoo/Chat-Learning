# ses_inbound

Receives brochure update emails via AWS SES, authenticates the sender, extracts
ZIP attachments, and writes the contained XML/PDF files to a staging bucket.

Operations guide: [`docs/runbooks/ses_brochure_inbox.md`](../../../docs/runbooks/ses_brochure_inbox.md)

## Flow

```
renate@drv-bund.de (manual send)
  -> brochures@mail.digibro-team.de
  -> SES receipt rule (eu-central-1)
  -> S3 inbox bucket        (raw MIME, 365-day retention, versioned)
  -> Lambda                 (authenticate, parse MIME, extract ZIP)
  -> S3 staging bucket      (extracted XML/PDF, awaiting ETL handoff)
  -> reply email to sender  (confirmation or error)
```

The staging bucket is deliberately **not** the ETL source bucket. Handoff into
the ETL pipeline is a separate, explicit step.

## Prerequisites

### Bootstrap IAM (per environment, operator-applied)

This module creates a Lambda execution role that carries the
`ki-lab-digibro-${env}-permissions-boundary` boundary. The boundary must already
allow the runtime actions below, otherwise `tofu apply` fails or the Lambda
fails at runtime. These were added for **dev** in `renate/bootstrap` MRs !40,
!42 and !43:

| Requirement                                           | Where                                                           |
| ----------------------------------------------------- | --------------------------------------------------------------- |
| `ses:*` receipt rule/identity management (apply role) | `modules/tofu_ci_roles/platform.tf`                             |
| `sns:*` topic management (apply role)                 | `modules/tofu_ci_roles/platform.tf`                             |
| `lambda:*` function management (apply role)           | `modules/tofu_ci_roles/platform.tf`                             |
| `iam:PassRole` to `lambda.amazonaws.com` (apply role) | `modules/tofu_ci_roles/platform.tf`                             |
| `route53:ChangeResourceRecordSets` (apply role)       | `modules/tofu_ci_roles/dns.tf`, `enable_dns_permissions = true` |
| `sns:Publish` in the boundary                         | `modules/tofu_ci_roles/permissions-boundary.tf`                 |
| `ses:SendEmail` in the boundary                       | `modules/tofu_ci_roles/permissions-boundary.tf`                 |
| `xray:Put*` in the boundary                           | `modules/tofu_ci_roles/permissions-boundary.tf`                 |

`env_name` is validated to `dev` for exactly this reason. Before using the
module in another environment, port the bootstrap changes to that account and
widen the validation.

### Other

- Route53 public hosted zone for the parent domain must exist.
- SES email receiving must be available in the target region (`eu-central-1` is).
- While SES is in the sandbox, every reply recipient must be a verified SES
  identity (`aws sesv2 create-email-identity --email-identity <addr>`).

## Security model

Sender authentication has three layers, all of which must pass:

1. **SES verdicts** — `spfVerdict`, `dkimVerdict` and `dmarcVerdict` must all be
   `PASS`. SES computes these; a client cannot forge them.
2. **Envelope sender allowlist** — the SMTP `MAIL FROM` address (what SPF/DMARC
   actually authenticated) must be in `allowed_senders`.
3. **Header/envelope match** — the `From:` header must equal the envelope
   sender, so a passing SPF check for one domain cannot display another.

Additional hardening:

- Inbox bucket policy scopes the SES `s3:PutObject` grant with both
  `AWS:SourceAccount` and `AWS:SourceArn` (confused-deputy).
- `aws_lambda_permission` sets `source_arn` to the specific receipt rule.
- Both buckets deny requests with `aws:SecureTransport = false`.
- `ses:SendEmail` is scoped to the receiving domain identity plus the explicit
  `allowed_senders` identities — no account-wide wildcard.
- ZIP extraction caps per-file size, cumulative decompressed size, and entry
  count (compression bombs).
- `Message-ID` is sanitized before use in S3 keys (path traversal).
- The handler never raises: SES retries async invocations, which would
  double-write attachments.

## SES active receipt rule set

SES allows exactly **one** active receipt rule set per account and region.
`manage_active_rule_set` therefore defaults to `false`. Check what is active
before enabling it:

```bash
aws ses describe-active-receipt-rule-set --region eu-central-1
```

If another rule set is active and must stay active, add a rule to that set
instead of activating this one.

## Inputs

| Variable                 | Type           | Default | Description                                                    |
| ------------------------ | -------------- | ------- | -------------------------------------------------------------- |
| `env_name`               | `string`       | —       | Environment name. Validated to `dev` (see Prerequisites).      |
| `account_id`             | `string`       | —       | AWS account ID; checked by a plan-time precondition.           |
| `hosted_zone_id`         | `string`       | —       | Route53 hosted zone of the parent domain.                      |
| `domain_name`            | `string`       | —       | Subdomain used for SES receiving, e.g. `mail.digibro-team.de`. |
| `recipient_address`      | `string`       | —       | Address to accept mail for; also the reply `From`.             |
| `allowed_senders`        | `list(string)` | —       | Authorised envelope senders. Others are quarantined.           |
| `alert_emails`           | `list(string)` | —       | Exactly the two official mailbox subscribers for this Dev SES workflow. |
| `manage_active_rule_set` | `bool`         | `false` | Activate the created receipt rule set (see warning above).     |
| `additional_tags`        | `map(string)`  | `{}`    | Extra tags merged into all resources.                          |

## Alert recipient policy

This dev-only module routes **only SES brochure-workflow alerts**. It does not
route generic Dev monitoring alerts. Terraform manages exactly these official
mailboxes:

- `renate@drv-bund.de`
- `ki-reha-anwendungsbetrieb@drv-bund.de`

Do not add personal addresses to `alert_emails`. A person who needs optional
notifications creates and confirms a personal SNS subscription through the
authorized AWS Console/IAM process; that subscription intentionally remains
outside Terraform. The system-wide Prod alert-routing policy is separate from
this module.

## Outputs

| Output                            | Description                  |
| --------------------------------- | ---------------------------- |
| `inbox_bucket_arn`                | ARN of the raw inbox bucket  |
| `inbox_bucket_name`               | Name of the raw inbox bucket |
| `staging_bucket_arn`              | ARN of the staging bucket    |
| `staging_bucket_name`             | Name of the staging bucket   |
| `processing_lambda_arn`           | ARN of the processor Lambda  |
| `processing_lambda_function_name` | Name of the processor Lambda |
| `sns_topic_arn`                   | ARN of the alert SNS topic   |

## Usage

```hcl
module "ses_inbound" {
  source     = "../../modules/ses_inbound"
  env_name   = "dev"
  account_id = "831926590742"

  hosted_zone_id    = "Z05955572KK17DXDISFXL"
  domain_name       = "mail.digibro-team.de"
  recipient_address = "brochures@mail.digibro-team.de"

  allowed_senders = ["renate@drv-bund.de"]

  alert_emails = [
    "renate@drv-bund.de",
    "ki-reha-anwendungsbetrieb@drv-bund.de",
  ]

  providers = {
    aws = aws.platform
  }
}
```

## Extension points

- `verify_signature()` in `lambda/handler.py` is a no-op stub for issue #558
  (S/MIME signature verification). It runs after sender authentication and
  before attachment extraction; raising from it halts processing.

## Testing

```bash
cd terraform/modules/ses_inbound/lambda
AWS_DEFAULT_REGION=eu-central-1 uv run pytest tests/ -v
```
