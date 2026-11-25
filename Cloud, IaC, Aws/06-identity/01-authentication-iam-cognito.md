---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 6
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Authentication, IAM roles, and Cognito

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../05-compute/02-ecs-fargate-and-choices.md) · [Next lesson](../06-identity/02-organizations-and-policy-layers.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Authentication establishes an identity; authorization decides what that identity may do.

## Learning objectives

Distinguish the app user, application runtime, and deployment job, and understand why they need different permissions.

## Why it matters

“The request is authenticated” is not enough to prove it may read another person’s conversation or modify infrastructure.

## Mental model

**IAM** controls access to AWS resources. A user is one kind of identity; a **role** can be assumed by an allowed identity and used through temporary credentials.

For a role, distinguish:

- **Trust policy:** who may assume this role?
- **Permissions policies:** what actions may this role perform on which resources?

**Cognito** provides application-user identity features. A user pool can support sign-in and issue tokens. An API must validate the appropriate token and enforce application-specific authorization. Cognito identity pools are a separate feature for obtaining AWS credentials; not every app needs one.

## Worked example and walkthrough

Our Helpdesk has three identities:

| Identity | Example task | Suitable permissions |
| --- | --- | --- |
| Signed-in user | Read their conversation | Application authorization for their records |
| Lambda execution role | Read/write conversation data | Limited database and model-service access |
| CI deployment role | Update infrastructure/code | Deployment actions for the target environment |

1. A person signs in.
2. The browser sends a token with its API request.
3. The configured authorizer/backend validates the token.
4. Application logic checks that the person may access the requested session.
5. Lambda calls DynamoDB using its own execution role.

The Lambda role does not automatically encode each user’s conversation permissions. The application must preserve that boundary.

Illustrative permissions-policy fragment:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject"],
  "Resource": "arn:aws:s3:::example-faq-bucket/*"
}
```

This expresses permission to read objects in a named bucket. It is not a complete policy or runnable setup; other policy layers can still restrict access. An ARN is AWS’s structured resource identifier.

## Common mistakes

An ID token and an access token have different purposes. Configure the API’s intended token type and validation rules; do not accept any token simply because it looks like a JWT.

Giving the runtime the deployment role unnecessarily lets application code change infrastructure.

## Practice

A user is signed in but requests another user’s session ID. What check is still required? Expected: authorization relating the authenticated user to that session.

## Self-check

- [ ] I can distinguish trust from permissions.
- [ ] I can identify user, runtime, and CI identities separately.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [IAM policies](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html)
- [IAM roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html)
- [Cognito overview](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
