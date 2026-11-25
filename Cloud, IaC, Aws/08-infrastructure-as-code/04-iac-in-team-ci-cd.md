---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 8
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# IaC in a team pipeline: validate, plan, apply, build, deploy

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../08-infrastructure-as-code/03-cdk-cloudformation-and-sdk.md) · [Next lesson](../09-putting-it-together/01-runtime-and-delivery-journeys.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** A delivery pipeline turns reviewed source changes into tested artifacts and authorized infrastructure or application updates.

## Learning objectives

Explain what each stage contributes, where OIDC fits, and why a successful commit does not guarantee a production deployment.

## Why it matters

When reading CI YAML, first identify the purpose of a job, its inputs, its target, and its permissions. Shell commands become easier to understand once those are clear.

## Mental model

GitLab reads pipeline configuration and creates eligible jobs. **Runners** execute those jobs in configured environments. GitLab does not create an entirely new runner merely because a repository contains YAML.

A stage name labels a phase; the job’s script performs the actual work. Rules, dependencies, manual gates, and includes determine the real execution graph.

The following is a fictional scheme, not a reconstruction of any private pipeline:

| Phase | Typical work | Result to inspect |
| --- | --- | --- |
| Validate | Formatting, linting, tests, config checks | Failures and test results |
| Tofu plan | Compare desired and observed infrastructure | Proposed changes |
| Tofu apply | Apply approved infrastructure operations | Resource updates/state |
| Build | Package frontend/backend/container | Versioned artifact |
| Deploy | Install or select the artifact in an environment | Running release |
| Post-deploy | Smoke tests and monitoring checks | Evidence the release works |

## Worked example and walkthrough

You change a backend function and add a storage resource.

1. Push a feature branch and open a merge request.
2. Validation checks code and configuration.
3. A plan job shows what infrastructure would change.
4. Teammates review code, plan, target environment, and any replacement.
5. An authorized job obtains temporary AWS credentials through OIDC.
6. Apply provisions the required infrastructure.
7. Build produces a versioned backend artifact.
8. Deployment updates the application to use that artifact.
9. A smoke test checks a small real interaction.

The exact sequence depends on dependencies. For example, a CDK stack deploying a function may need its artifact built **before** infrastructure deployment. “Apply always precedes build” is not a universal rule.

## Reading the shell commands

Illustrative Bash commands, not a complete executable pipeline:

```bash
tofu fmt -check
tofu validate
tofu plan -out=reviewed.tfplan
npm ci
npm run build
uv run pytest
```

- The first three inspect IaC and create a proposal; init/configuration is assumed.
- `npm ci` installs locked JavaScript dependencies.
- `npm run build` runs the project-defined build script; its meaning is in `package.json`.
- `uv run pytest` runs tests in the Python project environment.

These commands are programs, not built-in meanings of stage names. The runner image must contain required tools. Custom scripts can perform additional steps.

## Promotion and environment identity

Promotion means taking an intended release to the next environment. Teams often reuse the same verified artifact rather than rebuilding different bytes for production.

Code, data, and ingestion/ETL can have separate versions. A working application release does not prove a new knowledge dataset has been approved.

The **deployment role** changes resources. The deployed application’s **runtime role** serves users. They should not be confused.

## Common mistakes

A green pipeline proves only what its executed jobs checked. Skipped jobs, missing tests, and incorrect environment selection remain possible.

Do not assume rollback of code also reverses database migrations or restores deleted data. Define recovery for each kind of change.

## Practice

A job is called `deploy-prod` but its role and variables target QA. Which is authoritative? Expected: the actual configuration and credentials; the name alone proves nothing.

## Self-check

- [ ] I can explain what each phase produces.
- [ ] I can identify where deployment identity is established.
- [ ] I can explain why stage order depends on dependencies.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [GitLab pipeline configuration](https://docs.gitlab.com/ci/yaml/)
- [GitLab runners](https://docs.gitlab.com/ci/runners/)
- [GitLab environments](https://docs.gitlab.com/ci/environments/)
- [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci)
- [uv projects](https://docs.astral.sh/uv/guides/projects/)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
