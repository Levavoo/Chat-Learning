---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 6
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# AWS Organizations, SCPs, and different kinds of policies

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../06-identity/01-authentication-iam-cognito.md) · [Next lesson](../06-identity/03-oidc-ci-identity.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Organization-level controls set boundaries, while identity permissions grant actions within applicable boundaries.

## Learning objectives

Distinguish an SCP from an IAM group policy and Windows Group Policy.

## Why it matters

A deployment role can have an Allow policy and still be blocked by organisation-level rules. Knowing the policy layer helps explain why.

## Mental model

**AWS Organizations** manages multiple AWS accounts together. Accounts can be grouped into **organizational units (OUs)**. Controls can be applied through that hierarchy.

A **service control policy (SCP)** limits the maximum permissions available to affected principals in member accounts. It does not itself grant an identity permission to perform an action.

An **IAM group policy** gives permissions to IAM users who belong to that group. IAM groups do not contain roles or other groups.

**Windows Group Policy** configures Windows user/computer settings, for example workstation settings in a domain. Similar wording does not mean it is an AWS authorization mechanism.

| Policy | Main question |
| --- | --- |
| IAM role permissions | What may this role do? |
| IAM role trust | Who may assume this role? |
| SCP | What is permitted within this organisational boundary? |
| IAM group policy | What permissions do member IAM users receive? |
| Windows Group Policy | Which Windows settings apply? |

## Worked example and walkthrough

Suppose a production account belongs to an OU where an SCP denies deleting a protected class of resource.

1. The deployment job obtains its AWS role.
2. The role’s policy permits the relevant service operations.
3. The job attempts a deletion.
4. The applicable SCP deny prevents it.

The role’s Allow does not override that deny. Removing the SCP deny would not itself grant deletion; identity and other applicable policies still matter.

For a beginner’s model, think “permission must survive all relevant checks”. The complete AWS evaluation includes resource policies, boundaries, sessions, and exceptions, so avoid treating one tiny formula as the whole engine.

## Common mistakes

SCPs do not govern the management account in the same way as member accounts, and service-linked roles have documented exceptions. “An SCP controls absolutely every AWS action everywhere” is too broad.

OUs are account groupings, not teams of human users. An environment name such as QA does not automatically create an OU.

## Practice

Can attaching an SCP containing an Allow statement give a new role access to S3 by itself? Expected: no. An SCP is a boundary, not a standalone grant.

## Self-check

- [ ] I can distinguish all three similarly named policy concepts.
- [ ] I can explain how an IAM Allow can still be blocked.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [Service control policies](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_scps.html)
- [IAM user groups](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_groups.html)
- [Windows Group Policy](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/group-policy/group-policy-overview)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
