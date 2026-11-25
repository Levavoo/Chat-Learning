---
type: library-index
kind: concept
technology: Cloud, IaC, and AWS
status: planned
tags: [cloud, aws, infrastructure, learning]
---

# Cloud, IaC, and AWS

> How does an application run in AWS, and how does a team change it safely?

## Classification and scope

This is a **concept** library index connecting application architecture, cloud services, networking, and infrastructure as code. It is a learning scheme, not a completed lesson. All lessons below remain planned.

Use general examples and public documentation rather than workplace-specific code. Build on the [Git and GitHub library](../Git%20and%20GitHub%20library/README.md).

## Learning sequence

| Chapter | Planned lessons, in order | Team relevance |
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

## Questions the lessons must resolve

- How can S3 host a website without us running a server instance?
- What does serverless mean, and what does the team still manage?
- How does a cache relate to CDN edge locations?
- How do mainframe applications fit alongside modern web applications?
- Why are mainframes, monoliths, microservices, and serverless different dimensions?
- What distinguishes a network ACL, security group, IAM policy, SCP, and Windows Group Policy?
- Which tool defines a resource, and which code calls its API?

## Study approach

- [ ] Start with lesson 1.1, using one small application as a running example.
- [ ] Create one lesson at a time with explanations, examples, diagrams where useful, and self-checks.
- [ ] Keep application state distinct from network connection state.
- [ ] Explain BM25 as an algorithm, not an AWS service.
- [ ] Use “virtual private gateway (VGW)” for the intended “VPG gateway” topic.
- [ ] Finish with separate user-request and developer-deployment diagrams.

## Navigation

- [[Home]]
- [[Terms]]
- [[Glossary]]
- [Learnpaper template](../Templates/Learnpaper.md)
