---
type: learnpaper
kind: tool
technology: Cloud, IaC, and AWS
chapter: 8
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# CDK versus SDK, and where CloudFormation fits

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../08-infrastructure-as-code/02-plan-apply-state-and-drift.md) · [Next lesson](../08-infrastructure-as-code/04-iac-in-team-ci-cd.md)

This is a **tool** lesson: it compares development tools and the different operations they perform.

> **In one sentence:** CDK defines infrastructure that CloudFormation manages; an SDK lets a program call service APIs directly.

## Learning objectives

Recognise infrastructure-defining code versus runtime service calls, even when both are written in a programming language.

## Why it matters

A TypeScript file can define a bucket, while a Python file reads a document from it. Both mention S3 but operate at different points in the project lifecycle.

## Mental model

The **AWS SDK** is a set of client libraries for AWS APIs. Python’s AWS SDK is Boto3. Applications commonly use SDK calls while handling requests.

The **AWS CDK** is an infrastructure framework. CDK code builds a model of resources. **Synthesis** produces a CloudFormation template and related deployment assets. **CloudFormation** is the AWS service that provisions and tracks the stack’s resources.

CDK uses programming-language features to construct infrastructure definitions. Executing CDK code to synthesize a template is not the same as executing your chatbot backend.

## Worked example: the same bucket from two viewpoints

Illustrative CDK v2 TypeScript fragment, inside a configured stack:

```typescript
import * as s3 from "aws-cdk-lib/aws-s3";

const documents = new s3.Bucket(this, "Documents", {
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
});
```

This defines a bucket construct. Synthesis creates a corresponding infrastructure definition; deployment asks CloudFormation to create/update resources.

Illustrative Python runtime fragment, requiring Boto3, credentials, a real bucket, and a real object:

```python
import boto3

s3 = boto3.client("s3")
response = s3.get_object(
    Bucket="example-existing-faq-bucket",
    Key="faq/password-reset.txt",
)
text = response["Body"].read().decode("utf-8")
```

This reads an existing object now. It does not declare a managed infrastructure stack. Neither fragment has been deployed or run here.

## Step-by-step walkthrough

**Infrastructure path:** developer changes CDK → CDK synthesizes a template → deployment submits it → CloudFormation performs operations.

**Runtime path:** user asks a question → backend SDK call reads a document → backend uses the text.

An SDK can also create resources; “SDK only reads data” would be wrong. The key difference is direct API operations versus the declarative resource lifecycle supplied by an IaC system.

## OpenTofu and CDK together

A team might let OpenTofu own shared networking and CDK own application functions. That is an ownership choice, not a universal rule.

Pass agreed identifiers between layers. Referencing an existing resource does not necessarily mean taking ownership of its lifecycle. Avoid independently declaring the same bucket or policy under two managers.

CloudFormation tracks its own stacks; it does not use OpenTofu’s state file.

## Common mistakes

A CDK source-code diff is not the complete deployed-resource diff. Generated resources and defaults can change the result, so inspect synthesized changes.

“Application IaC” is still infrastructure code supporting the application, not the request-processing code itself.

## Practice

Which tool is suitable for “create the table as part of deployment” versus “read one item for this request”? Expected: an IaC tool for managed provisioning; an SDK call for runtime access.

## Self-check

- [ ] I can trace CDK through CloudFormation.
- [ ] I can explain why two files mentioning S3 can have different roles.
- [ ] I can explain one resource-ownership conflict to avoid.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [AWS CDK guide](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
- [CDK synthesis](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-synth.html)
- [CloudFormation concepts](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-whatis-concepts.html)
- [Boto3 S3 get_object](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/get_object.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
