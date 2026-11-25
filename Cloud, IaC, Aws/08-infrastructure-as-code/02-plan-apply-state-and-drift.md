---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 8
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Plan, apply, state, and drift

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../08-infrastructure-as-code/01-desired-state-and-providers.md) · [Next lesson](../08-infrastructure-as-code/03-cdk-cloudformation-and-sdk.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** A plan proposes infrastructure operations, apply performs them, and state records the tool’s mapping between configuration and managed resources.

## Learning objectives

Read the purpose of common OpenTofu commands, understand why state is shared carefully, and recognise replacement or drift before approving a change.

## Why it matters

A small code change can have a large infrastructure effect. The plan is a concrete review artifact, not just a green pipeline box.

## Mental model: three different things

| Thing | Meaning |
| --- | --- |
| Configuration files | What we declare that we want |
| Actual AWS resources | What currently exists |
| IaC state | Recorded resource identities and attributes used by the tool |

State is not the application’s conversation history. It can map a configuration address such as `aws_s3_bucket.faq_documents` to a particular real bucket.

During normal planning, the tool reads relevant remote information and compares it with the configuration and state. **Drift** is divergence caused by changes outside the expected IaC workflow or other differences from the managed configuration.

## Worked example and walkthrough

Illustrative Bash sequence for an already configured, authorized learning environment. These commands have not been run here:

```bash
tofu init
tofu fmt -check
tofu validate
tofu plan -out=reviewed.tfplan
tofu show reviewed.tfplan
tofu apply reviewed.tfplan
```

1. **init:** prepares the working directory, including the configured backend and providers.
2. **fmt -check:** checks formatting; it does not prove the design is correct.
3. **validate:** checks configuration validity; it is not a guarantee that AWS will accept every operation.
4. **plan -out:** calculates proposed operations and saves a plan.
5. **show:** displays the saved plan for review.
6. **apply:** carries out the saved plan. Supplying a saved plan does not provide the normal interactive approval prompt.

In a team pipeline, authorization and review happen before the apply job is allowed to execute. Do not run the final command merely to learn what it means.

A simplified plan summary might look like:

```text
+ create a new resource
~ update a resource in place
- destroy a resource
-/+ destroy and replace a resource
```

Actual output contains resource names and detailed attribute changes. Replacement deserves particular attention: will data survive, will names change, and will there be an interruption?

## Why teams share state

If two laptops each maintain unrelated local state for the same intended infrastructure, they can disagree about what they own. Teams usually configure a **remote state backend** and suitable locking/access controls.

Lock support depends on the selected backend. A lock helps prevent conflicting concurrent state-changing operations. It does not replace team coordination or magically lock every AWS console action. Separate environments need clearly separated state and target configuration.

State and saved plans can contain sensitive values. Keep them out of ordinary Git commits and control artifact access and retention. A provider lock file records dependency selections; it is not the infrastructure state file.

## Drift example

The declared tag is `Purpose = "Learning"`, but someone changes it in the console.

1. The next plan observes the current value.
2. It can propose restoring the declared value.
3. The team decides whether the manual change should instead become the new declaration.
4. They review and apply the agreed configuration.

The tool is not deciding the business intention; people still decide which state is correct.

## Common mistakes and failure modes

A plan is time-sensitive. The environment or configuration can change before apply, and a saved plan may become stale or fail. “It was reviewed last week” is not enough evidence for today’s target.

Apply is not a database transaction across every AWS service. Some operations may succeed before another fails. Inspect the result and produce a fresh plan; do not assume everything rolled back.

Reverting Git does not immediately restore deleted data. Backups and recovery procedures are separate from configuration history.

## Practice

A plan says one resource will be replaced although you changed only one line. What should you investigate? Expected: the replacement-triggering attribute, data/lifecycle consequences, dependencies, and target environment.

## Self-check

- [ ] I can distinguish configuration, state, and real infrastructure.
- [ ] I can explain why plan is reviewed before apply.
- [ ] I can explain why failed apply does not imply no changes occurred.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [OpenTofu init](https://opentofu.org/docs/cli/commands/init/)
- [OpenTofu plan](https://opentofu.org/docs/cli/commands/plan/)
- [OpenTofu apply](https://opentofu.org/docs/cli/commands/apply/)
- [OpenTofu state](https://opentofu.org/docs/language/state/)
- [State locking](https://opentofu.org/docs/language/state/locking/)
- [Sensitive state data](https://opentofu.org/docs/language/state/sensitive-data/)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
