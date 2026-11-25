---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 1
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Virtual machines, containers, and serverless

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../01-foundations/02-hosting-static-dynamic.md) · [Next lesson](../01-foundations/04-aws-accounts-and-locations.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** These approaches change how software is packaged and how much of its execution environment your team manages.

## Learning objectives

Locate the physical computers beneath cloud services and explain who manages each layer.

## Why it matters

“Serverless” is easier to understand when compared with renting a virtual machine. It changes operational responsibilities; it does not remove computation.

## Mental model

A **virtual machine (VM)** acts like a separate computer with its own operating system. On an EC2 VM, your team normally chooses and maintains the guest operating system and starts the application processes.

A **container** packages an application and its dependencies. Containers run as isolated processes using a host kernel. A container image is a package, not a running computer. Someone must provide the host.

With **serverless compute**, the provider manages the underlying servers and execution capacity. Your team supplies code or a container and configures the service. AWS Lambda and AWS Fargate expose different interfaces for this.

| Arrangement | Your main deployment unit | Who operates the host OS? |
| --- | --- | --- |
| EC2 VM | Software installed on a VM | Your team |
| Container on your EC2 VM | Container image | Your team |
| Container on Fargate | Container task | AWS |
| Standard Lambda function | Function package or supported image | AWS |

Your responsibility for application dependencies, data, permissions, and configuration remains in every arrangement.

## Worked example and walkthrough

To run the same FAQ backend:

1. **EC2:** create a VM, install Python, install dependencies, configure a process to start and restart.
2. **Fargate:** build a container image, define a task, configure a service to keep tasks running.
3. **Lambda:** package a handler, configure an event source, let Lambda invoke the handler when work arrives.

These are alternatives, not three required steps.

Do not imagine that every request must move to a new random server. Providers can reuse capacity and running environments. “No permanently assigned server that I manage” is a useful starting thought; “nothing persists anywhere” is not.

## Common mistakes

Serverless does not automatically mean free when idle for every service, infinite capacity, or no operational work. Quotas, scaling behaviour, logging, failure handling, and billing still matter.

Containerization alone does not make an application serverless.

## Practice

Your team patches Linux on the host running its containers. Is that host management serverless? Expected: no; the containers may simplify packaging, but the team still operates the host.

## Self-check

- [ ] I can explain where serverless code physically runs.
- [ ] I can name responsibilities that remain with developers.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [AWS shared responsibility](https://aws.amazon.com/compliance/shared-responsibility-model/)
- [Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
