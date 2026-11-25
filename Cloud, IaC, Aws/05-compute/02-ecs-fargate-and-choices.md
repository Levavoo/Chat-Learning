---
type: learnpaper
kind: service
technology: Cloud, IaC, and AWS
chapter: 5
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# EC2, ECS, and Fargate: choosing how work runs

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../05-compute/01-lambda-execution.md) · [Next lesson](../06-identity/01-authentication-iam-cognito.md)

This is a **service** lesson: it explains managed AWS capabilities and how an application uses them.

> **In one sentence:** EC2 gives you virtual machines, ECS coordinates container workloads, and Fargate supplies managed compute for supported container tasks.

## Learning objectives

Distinguish a container scheduler from its compute capacity and compare suitable workload shapes.

## Why it matters

A Dockerfile explains packaging, but does not fully explain how production keeps the application running.

## Mental model

An **image** is a packaged application. A running container uses that image. **ECS** defines and coordinates tasks; a task definition describes settings such as image, resources, and roles. An ECS service can maintain a desired number of running tasks.

With **Fargate**, AWS operates the underlying compute hosts. With ECS on **EC2**, the team also manages the VM capacity used by tasks. Fargate is serverless container compute; your application can still be a long-running server process inside the container.

## Worked example and walkthrough

Suppose our backend needs to keep a web-server process running.

1. CI builds a container image containing Python and the application.
2. CI publishes the image to a registry.
3. Deployment updates an ECS task definition to reference that image.
4. An ECS service starts replacement tasks on Fargate.
5. Configured health checks determine whether the new tasks are ready.
6. A load balancer sends requests to healthy tasks.

AWS manages the host. The team still chooses application dependencies, task sizing, scaling policy, network settings, and application health behaviour.

| Workload | Option worth evaluating | Reason |
| --- | --- | --- |
| Short event-driven request handling | Lambda | Function invocation model |
| Existing container web server | ECS with Fargate | Keep the container process running |
| Special OS or host requirements | EC2 | More machine-level control |
| Batch container work | ECS tasks/Fargate | Run a task to completion |

This table is a starting point, not an automatic decision algorithm. Compare operational constraints, supported features, latency, duration, and costs for the actual workload.

## Common mistakes

“Serverless” does not imply that every container stops between requests. A Fargate service may keep tasks running continuously.

Container images can contain outdated dependencies even when AWS patches the host. An image tag also may be mutable; deployment needs an unambiguous artifact reference.

## Practice

Your application requires installing a custom kernel module. Which model deserves investigation? Expected: a host-controlled option such as EC2; managed function/task environments do not provide arbitrary host control.

## Self-check

- [ ] I can distinguish ECS from Fargate.
- [ ] I can explain what a team still manages for a container task.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [AWS Fargate](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Fargate.html)
- [ECS services](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs_services.html)
- [EC2 overview](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
