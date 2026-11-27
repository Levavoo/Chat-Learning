# modules/digibro/oidc

Provisions the GitLab CI OIDC identity provider in a digibro AWS account,
enabling GitLab CI jobs to assume IAM roles in that account via
`sts:AssumeRoleWithWebIdentity` without long-lived credentials.

## Context

When a GitLab CI job runs, GitLab issues a signed JWT containing claims about
the pipeline: project path, ref, environment, and others. The job can exchange
that token for temporary AWS credentials by calling
`sts:AssumeRoleWithWebIdentity`. AWS validates the token by fetching the
provider's JWKS endpoint, verifying the signature, and checking that the
`iss` and `aud` claims match the registered provider.

`aws_iam_openid_connect_provider` establishes that trust at the account level.
It tells IAM which issuer URL to accept tokens from and which audience values
are valid. Without it, any `sts:AssumeRoleWithWebIdentity` call referencing
this GitLab instance is rejected regardless of the role's trust policy.

This resource is therefore a hard prerequisite for every IAM role that grants
CI jobs access to this account. `modules/digibro/runner_role/` (TKT-M57)
depends on `provider_arn` from this module as its trust-policy principal.

## Managed resources

- `aws_iam_openid_connect_provider.gitlab_ci` — registers
  `https://gitlab.kilab-platform.de` as a trusted OIDC issuer. The audience
  is the GitLab instance URL, matching the `aud` claim GitLab embeds in CI
  job tokens.
- `data.aws_caller_identity.current` — read at plan time to enforce the
  account precondition. The plan fails immediately if the assumed role belongs
  to the wrong account.

## Out of scope

- The `aws` provider — must be declared in the calling root; child modules
  cannot declare providers in OpenTofu.
- IAM deploy roles — `modules/digibro/runner_role/` (TKT-M57). That module
  takes `module.oidc.provider_arn` as an input.
- ECR repositories — `modules/digibro/ecr/` (TKT-M58).

## Interface

Inputs and outputs are defined in `variables.tf` and `outputs.tf`.

The required input is `account_id`. The `thumbprint` and `additional_tags`
inputs have defaults and can be omitted. The single output, `provider_arn`,
is the ARN of the created OIDC provider; pass it to `modules/digibro/runner_role/`
as the trust-policy principal.

## Calling roots

| Root | Account ID |
|------|------------|
| `terraform/live/digibro/dev/` | `831926590742` |
| `terraform/live/digibro/prod/` | `571600837515` |

## Adding a new digibro account

1. Copy `terraform/live/digibro/dev/` to `terraform/live/digibro/<env>/`.
2. Update `versions.tf`: set the correct S3 state bucket name and key.
3. Update `main.tf`: set `account_id` to the new account's ID.
4. Run `tofu init` and `tofu apply` from the new root directory.

## Thumbprint rotation

The `thumbprint` variable is the SHA1 fingerprint of the **root CA** at the
top of the GitLab instance TLS chain. It must be recomputed when the root CA
rotates — not on leaf-cert renewal.

> **AWS CA bundle note (May 2023+):** For well-known CAs (Let's Encrypt,
> DigiCert, etc.), AWS validates OIDC providers against its own managed CA
> bundle and ignores the thumbprint field. The thumbprint only becomes
> load-bearing if the provider's CA is not in that bundle. It must still be
> supplied as a non-empty value.

Recompute if the root CA rotates:

```bash
echo | openssl s_client \
  -servername gitlab.kilab-platform.de \
  -connect gitlab.kilab-platform.de:443 \
  -showcerts 2>/dev/null \
  | awk 'BEGIN{c=0} /BEGIN CERT/{c++; cert=""} c{cert=cert $0 "\n"} /END CERT/{last=cert} END{print last}' \
  | openssl x509 -fingerprint -sha1 -noout \
  | cut -d= -f2 | tr -d ':' | tr '[:upper:]' '[:lower:]'
```

The `-showcerts` flag and the `awk` step isolate the last certificate in the
chain (the root CA). Without `-showcerts`, `openssl s_client` outputs only
the leaf cert, which produces the wrong thumbprint.

Update `variable "thumbprint"` default in `variables.tf`, then `tofu apply`
in each thin root.

## See Also

- [docs/reference/aws_accounts.md](../../../../docs/reference/aws_accounts.md) — OIDC provider ARNs and thumbprint details
- [docs/runbooks/ci_aws_oidc_auth.md](../../../../docs/runbooks/ci_aws_oidc_auth.md) — deploy role creation and CI wiring
- [AWS IAM OIDC providers](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [GitLab CI cloud services: AWS](https://docs.gitlab.com/ci/cloud_services/aws/)
