# digibro/ecr

Provisions an ECR repository for Lambda container images in a digibro account.

Used by `terraform/live/digibro/dev/` and `terraform/live/digibro/prod/`.

## Resources

- `aws_ecr_repository.renate_lambda` -- repository named `renate-lambda`, IMMUTABLE
  tags, scan on push enabled, AES256 encryption (AWS-managed key)
- `aws_ecr_lifecycle_policy.renate_lambda` -- expires untagged images after 7 days;
  retains the last 20 images with a `v` tag prefix

The account precondition guards against applying in the wrong account. It compares
`var.account_id` against the caller identity at plan time and fails with a clear
error if they do not match.

## Inputs

| Name | Type | Description |
|------|------|-------------|
| `account_id` | `string` | AWS account ID. Verified by precondition at plan time. |
| `additional_tags` | `map(string)` | Extra tags merged into the resource tag set. |

## Outputs

| Name | Description |
|------|-------------|
| `repository_url` | ECR repository URL -- used in `buildah push` and Lambda `DockerImageCode.fromEcr()`. |
| `repository_arn` | ARN of the ECR repository. |

## Lifecycle policy rationale

Untagged images accumulate on every push. The 7-day expiry keeps storage costs
bounded without deleting images mid-deploy. The 20-image tagged retention covers
the last several releases and allows rollback without manual cleanup.
