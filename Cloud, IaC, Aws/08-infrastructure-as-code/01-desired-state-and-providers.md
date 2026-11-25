---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 8
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Infrastructure as Code: desired state and providers

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../07-ai-and-retrieval/02-ingestion-bm25-vectors-rag.md) · [Next lesson](../08-infrastructure-as-code/02-plan-apply-state-and-drift.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Infrastructure as Code describes infrastructure in version-controlled files so tools can propose and carry out changes through provider APIs.

## Learning objectives

Explain what IaC controls, distinguish desired configuration from application logic, and read a small resource declaration.

## Why it matters

A pull request can change what machines, storage, networking, or permissions exist. Reviewing the code and resulting plan makes those changes visible to teammates.

## Mental model

Without IaC, a person might create a bucket in the AWS console and later struggle to explain its exact settings.

With IaC, the team records the desired configuration in files. A tool compares that configuration with its state and information from the provider, builds a dependency graph, and proposes changes. Applying the proposal sends API requests.

**Terraform** and **OpenTofu** are IaC tools with a shared history and similar configuration concepts. OpenTofu is an open-source fork. They now evolve separately: verify compatibility before changing a real project between them.

Configuration commonly lives in `.tf` files written in **HCL**, a configuration language with blocks and attributes. These files are different from the YAML that tells GitLab which jobs to run. The command-line programs are named `tofu` and `terraform`; many basic commands have similar names, but project versions and compatibility still matter.

A **provider** is the integration that lets the tool manage a particular platform’s resource types. The AWS provider translates resource operations into AWS API interactions.

## Worked example

Illustrative HCL configuration fragment:

```hcl
resource "aws_s3_bucket" "faq_documents" {
  bucket = "example-helpdesk-faq-unique-name"

  tags = {
    Purpose = "Learning"
  }
}
```

This fragment is not a complete production configuration and has not been applied. A real setup needs tool/provider configuration, credentials, suitable names, and required security/operational settings.

Read it slowly:

1. `resource` declares something the tool will manage.
2. `aws_s3_bucket` identifies a resource type implemented by the AWS provider.
3. `faq_documents` is the local name in the configuration.
4. `bucket` requests the AWS bucket name.
5. `tags` supplies metadata.

The local name and AWS name are different. S3 naming rules and uniqueness constraints still apply.

Changing `Purpose` describes a desired metadata change. Changing a resource’s name may imply replacement or a different operation depending on that resource’s schema. **Read the plan rather than guessing from the size of the code edit.**

## How it fits the application

This code creates/configures a place where FAQ files can live. It does not, by itself, upload all documents or answer user questions.

Application code can later call S3 to read a document. Infrastructure code defines the bucket and its access arrangements. A delivery pipeline coordinates both sorts of work.

IaC is not generally a daemon continuously correcting every manual change. Someone or some automation must run the relevant planning/applying workflow.

## Common mistakes

“Declarative” does not mean harmless. A declaration can cause deletion or replacement.

A successful `git push` records configuration but changes AWS only if an authorized deployment process runs.

Do not have two independent IaC tools both manage the same resource’s settings without an explicit ownership design.

## Practice

A teammate changes a console setting manually. Has the Git file changed? Expected: no. The real infrastructure may now differ from the declared intention; that is a drift investigation.

## Self-check

- [ ] I can explain desired configuration versus actual resources.
- [ ] I can explain a provider’s role.
- [ ] I can distinguish infrastructure code from runtime application code.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [OpenTofu introduction](https://opentofu.org/docs/intro/)
- [OpenTofu resources](https://opentofu.org/docs/language/resources/)
- [Terraform introduction](https://developer.hashicorp.com/terraform/intro)
- [AWS provider S3 bucket resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3_bucket)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
