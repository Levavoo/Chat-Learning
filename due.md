---
type: learning-backlog
kind: other
status: open
created: 2026-11-27
tags: [questions, learning, cloud, containers, iac]
---

# Due — open learning questions

This is a **learning backlog**, classified as `other`: questions to clarify and organise into future lesson updates. It is not a completed lesson.

Keep questions unchecked until discussed and understood. Add further questions before finalising the lesson-expansion plan.

## 1. Runtimes

- [ ] What does “runtime” mean?
- [ ] How does a language runtime, such as Python, differ from a container runtime?
- [ ] What does a container runtime actually start and manage?

**Placement:** Add a foundational explanation before the deeper container material.

## 2. Container images, packages, and processes

- [ ] Why is it called a container “image” rather than simply a package?
- [ ] What is inside an image?
- [ ] How do an image, a running container, and an application process relate?

**Placement:** Expand [VMs, containers, and serverless](Cloud%2C%20IaC%2C%20Aws/01-foundations/03-vms-containers-serverless.md) with a dedicated container fundamentals lesson.

## 3. Linux namespaces and cgroups

- [ ] What are Linux namespaces, and what do they isolate?
- [ ] What are cgroups, and how do they control resource use?
- [ ] How do these mechanisms contribute to running containers?

**Placement:** New section in container fundamentals; use one simple example rather than kernel-level detail.

## 4. Paths and operating systems

- [ ] How do paths differ between Windows, Linux, and macOS?
- [ ] Which paths does an application see inside a container?
- [ ] How are host folders connected to container paths?
- [ ] What do containers solve about portability, and which OS differences still matter?

**Placement:** New practical lesson on host paths, container paths, mounts, and OS compatibility.

## 5. Lambda execution environments

- [ ] What is a reusable Lambda execution environment?
- [ ] Is it like a running instance? Where does that comparison stop being useful?
- [ ] What can remain between invocations, and what must not be relied on?
- [ ] How does reuse relate to cold and warm starts?

**Placement:** Expand [Lambda execution](Cloud%2C%20IaC%2C%20Aws/05-compute/01-lambda-execution.md), which already introduces reuse.

## 6. Lambda packaging and durable data

- [ ] What does “function package or supported image” mean for Lambda?
- [ ] How do the two deployment formats differ?
- [ ] What does “durable data” mean in the AWS context?
- [ ] How is durable storage different from process memory or temporary execution-environment storage?

**Placement:** Add separate packaging and data-persistence sections to the Lambda lesson; connect the latter to [S3 and DynamoDB](Cloud%2C%20IaC%2C%20Aws/04-storage-and-delivery/01-s3-hosting-and-dynamodb.md).

## 7. Orchestration

- [ ] What does an orchestrator do in general programming?
- [ ] What does a container orchestrator do?
- [ ] What is shared between those meanings, and what differs?

**Placement:** A short comparison linking [ECS/Fargate](Cloud%2C%20IaC%2C%20Aws/05-compute/02-ecs-fargate-and-choices.md) with [application/model orchestration](Cloud%2C%20IaC%2C%20Aws/07-ai-and-retrieval/01-bedrock-and-orchestration.md).

## 8. Batches and containers

- [ ] What is a batch, and what is a batch job?
- [ ] How does batch processing differ from a container?
- [ ] How can a batch job run inside a container?

**Placement:** Extend the batch discussion in [Mainframes and applications](Cloud%2C%20IaC%2C%20Aws/02-architecture/02-mainframes-and-applications.md), with a link to container workloads.

## 9. OpenTofu, Terraform, and CI stages

- [ ] Are plan and apply used by both OpenTofu and Terraform?
- [ ] How do tool commands differ from CI stages named “plan” and “apply”?
- [ ] Where can I inspect IaC state, and how do local and remote state locations differ?
- [ ] Create a dedicated introductory lesson entry for OpenTofu later.
- [ ] Create a dedicated introductory lesson entry for Terraform later.

**Placement:** Expand [Plan, apply, state, and drift](Cloud%2C%20IaC%2C%20Aws/08-infrastructure-as-code/02-plan-apply-state-and-drift.md) and connect it to [IaC in CI/CD](Cloud%2C%20IaC%2C%20Aws/08-infrastructure-as-code/04-iac-in-team-ci-cd.md). Retain a shared explanation of common concepts to avoid duplication.

## Next planning steps

- [ ] Collect additional questions.
- [ ] Consolidate overlaps and confirm a learning order.
- [ ] Decide which existing lessons to expand and which new notes to create.
- [ ] Add explanations and clear project examples only after the backlog is ready.

## Related notes

- [[Cloud, IaC, Aws/README|Cloud, IaC, and AWS]]
- [[Terms]]
- [[Glossary]]
