---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 1
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# AWS accounts, Regions, Availability Zones, and edge locations

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../01-foundations/03-vms-containers-serverless.md) · [Next lesson](../02-architecture/01-components-monolith-microservices.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Accounts separate ownership and permissions, while Regions, Availability Zones, and edge locations describe different geographical roles.

## Learning objectives

Distinguish an environment name from an AWS boundary and explain why location matters.

## Why it matters

Before a deployment, “which account and Region?” is as important as “which version?”. Correct code deployed to the wrong place is still the wrong change.

## Mental model

An **AWS account** is a boundary for resources, access, and billing attribution. A **Region** is a geographical area in which many services offer regional resources. A Region contains multiple **Availability Zones (AZs)**: separate infrastructure locations designed to reduce shared failure risks.

An **edge location** brings delivery or other supported services closer to users. A CloudFront edge location can serve cached files. It is not simply another name for an AZ.

Some services have a global scope; others are regional or have resources tied to an AZ. Check the service rather than assuming one location rule fits everything.

## Worked example and walkthrough

A fictional team has:

| Environment | Purpose | Example isolation |
| --- | --- | --- |
| Dev | Frequent integration and experimentation | Development AWS account |
| QA | Acceptance and release checks | QA AWS account |
| Prod | Real users and data | Production AWS account |

This is a possible arrangement, not a requirement. Another team may separate environments within one account.

Suppose QA and production use the same Region:

1. The deployment job selects production credentials.
2. It selects the configured Region.
3. IaC defines resources there, possibly across multiple AZs.
4. CloudFront can deliver eligible cached content nearer to users outside that Region.

The frontend cache being close to a user does not mean their database has moved there.

## Common mistakes

A branch named `dev` is a Git concept, not automatically an AWS environment. The pipeline connects branches or release versions to deployment targets.

Using multiple AZs does not automatically protect against every regional outage. Backups, recovery procedures, and application design are separate decisions. Data residency also requires examining the services and features actually used.

## Practice

You can view GitLab code but cannot deploy production. Is that inconsistent? Expected: no. Repository permissions and AWS deployment permissions are separate controls.

## Self-check

- [ ] I can distinguish account, Region, AZ, and edge location.
- [ ] I can explain why dev/QA/prod need explicit configuration.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [Regions and Availability Zones](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/using-regions-availability-zones.html)
- [CloudFront overview](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
