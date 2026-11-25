---
type: library-index
kind: concept
technology: Cloud, IaC, and AWS
status: draft
tags: [cloud, aws, infrastructure, learning]
---

# Cloud, IaC, and AWS

> How does an application run in AWS, and how does a team change it safely?

## Classification and scope

This **concept** library connects application architecture, cloud services, networking, identity, and infrastructure as code. It contains **23 beginner lessons across nine chapters**. Lessons are drafts for study and review, not a record of mastered topics.

One fictional **Helpdesk** web application provides the running example: a browser interface lets users ask questions about public FAQ documents. Its backend retrieves context, calls a model, and stores conversations. No lesson describes a private workplace deployment.

Build on the [Git and GitHub library](../Git%20and%20GitHub%20library/README.md). There are no required AWS deployments, costs, or new dependencies for reading this library. Code and shell examples are labelled as illustrative; they have not been deployed or executed here.

## Start here

Read [Application, process, server, and infrastructure](01-foundations/01-application-process-server.md), then follow the **Next lesson** links. Work through one lesson at a time. Most lessons take roughly 10–15 minutes with their question; allow longer for Lambda, OIDC, mainframes, and IaC.

Each lesson explains the mental model, its place in a project, a concrete example, common mistakes, and a small practice question with an expected answer. Try answering before reading the expected answer. Use the official sources when you want to go deeper; you do not need to read all of them first.

## Chapters

| Chapter | Lessons | What you should be able to explain |
| --- | --- | --- |
| [1. Foundations](01-foundations/README.md) | 4 | Identify what runs, where it runs, and who manages it. |
| [2. Application architecture](02-architecture/README.md) | 2 | Distinguish application boundaries from computing platforms. |
| [3. Networking](03-networking/README.md) | 3 | Trace reachability, traffic rules, name resolution, and request forwarding. |
| [4. Storage and delivery](04-storage-and-delivery/README.md) | 2 | Understand where files and records live, and how content reaches users. |
| [5. Compute](05-compute/README.md) | 2 | Understand how processes, functions, and containers execute. |
| [6. Identity and governance](06-identity/README.md) | 3 | Separate user, runtime, and deployment identities and their permissions. |
| [7. AI and retrieval](07-ai-and-retrieval/README.md) | 2 | Separate document preparation, search, orchestration, and inference. |
| [8. Infrastructure as Code](08-infrastructure-as-code/README.md) | 4 | Read infrastructure declarations and follow reviewed changes through deployment. |
| [9. Putting it together](09-putting-it-together/README.md) | 1 | Connect user requests with developer delivery without mixing their paths. |

## Find the questions that matter most

- **What does serverless actually mean?** Start with [VMs, containers, and serverless](01-foundations/03-vms-containers-serverless.md), then [Lambda execution](05-compute/01-lambda-execution.md).
- **How can S3 host a website?** Read [S3 hosting and DynamoDB](04-storage-and-delivery/01-s3-hosting-and-dynamodb.md), then [cache and CloudFront](04-storage-and-delivery/02-cache-cdn-cloudfront.md).
- **What is a mainframe in an application project?** Read [mainframes and applications](02-architecture/02-mainframes-and-applications.md).
- **How does a CI job gain an AWS identity?** Read [IAM and Cognito](06-identity/01-authentication-iam-cognito.md), then [OIDC CI identity](06-identity/03-oidc-ci-identity.md).
- **What does IaC do to real infrastructure?** Follow all four lessons in [Infrastructure as Code](08-infrastructure-as-code/README.md).
- **How do all these parts fit together?** Finish with [the user and developer journeys](09-putting-it-together/01-runtime-and-delivery-journeys.md).

## How to use this in a team

For any new term, ask: **What kind of thing is it? Where does it sit? What goes in and comes out? Which identity uses it? What could fail?**

When reading a real repository, use the lessons as a map rather than assuming it matches the fictional example. Confirm actual resource ownership, pipeline rules, environment targets, and access configuration from the project itself.

## Original scope coverage

| Chapter | Topics covered by the lessons | Team relevance |
| --- | --- | --- |
| 1. Foundations | 1.1 Application, process, server, infrastructure; 1.2 Hosting and static/dynamic content; 1.3 VMs, containers, serverless and responsibilities; 1.4 Accounts, Regions, AZs, edge locations | Identify what runs where and who manages it |
| 2. Application architecture | 2.1 Frontend/API/backend/database; 2.2 Monolith and modular monolith; 2.3 Microservices; 2.4 Mainframe applications, transactions, batch processing and integration; 2.5 Compare architecture with hosting platforms | Distinguish modules, services, and execution platforms |
| 3. Networking | 3.1 IP, ports, DNS, HTTP/HTTPS; 3.2 VPCs, subnets, routes; 3.3 Inbound/outbound; 3.4 Stateful/stateless filtering; 3.5 Security groups and ACLs; 3.6 Internet/NAT/virtual private gateways; 3.7 Route 53 and ELB | Diagnose reachability and traffic rules |
| 4. Storage and delivery | 4.1 Storage versus databases; 4.2 S3 and static hosting; 4.3 DynamoDB; 4.4 Cache, hits/misses, expiry and invalidation; 4.5 CDN, CloudFront and origins; 4.6 Complete website delivery | Locate data and understand cached responses |
| 5. Compute | 5.1 EC2 as a reference point; 5.2 Lambda execution and scaling; 5.3 ECS and Fargate; 5.4 Choose a workload execution model | Understand packaging, runtime, and failures |
| 6. Identity and governance | 6.1 Authentication/authorization; 6.2 IAM users, roles and policies; 6.3 Cognito; 6.4 Organizations and OUs; 6.5 SCPs versus IAM group policies and Windows Group Policy; 6.6 CI identity through OIDC | Understand developer, user, and deployment permissions |
| 7. AI and retrieval | 7.1 Inference versus orchestration; 7.2 Bedrock; 7.3 Document preparation; 7.4 BM25; 7.5 Vector/hybrid retrieval; 7.6 Complete chatbot request | Separate retrieval, model, and application problems |
| 8. Infrastructure as Code | 8.1 Desired infrastructure; 8.2 Terraform/OpenTofu and providers; 8.3 Plan/apply/state/drift; 8.4 SDK versus CDK; 8.5 CDK/CloudFormation; 8.6 Resource ownership across tools; 8.7 IaC in CI/CD | Read plans, review changes, and locate resource definitions |
| 9. Integration | 9.1 User request journey; 9.2 Developer change journey | Connect runtime architecture to delivery |

The original subtopics are grouped into 23 substantive lessons so closely related ideas can be learned together. Mainframe/platform versus application structure, network versus application state, BM25 versus AWS services, and resource ownership are distinguished explicitly.

## Study progress

- [ ] Chapter 1: Foundations
- [ ] Chapter 2: Application architecture
- [ ] Chapter 3: Networking
- [ ] Chapter 4: Storage and delivery
- [ ] Chapter 5: Compute
- [ ] Chapter 6: Identity and governance
- [ ] Chapter 7: AI and retrieval
- [ ] Chapter 8: Infrastructure as Code
- [ ] Chapter 9: Putting it together

## Navigation

- [[Home]]
- [[Terms]]
- [[Glossary]]
- [Learnpaper template](../Templates/Learnpaper.md)
