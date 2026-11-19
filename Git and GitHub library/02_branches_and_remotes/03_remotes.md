---
type: learnpaper
kind: tool
domain: version-control
technology: Git and GitHub
chapter: 02_branches_and_remotes
level: beginner
status: draft
tags: [git, github, branches-and-remotes]
---

# Remote Repositories

> **In one sentence:** A remote is a named connection to another Git repository; origin is a common name.

## Learning objectives

- Explain the role of this concept in version control or GitHub collaboration.
- Use or interpret the example below and understand what changes locally versus remotely.
- Identify a common mistake before making it in a real repository.

## Why it matters

A remote is a named connection to another Git repository; origin is a common name. It helps make changes traceable and collaboration safer. The goal is to understand both the command and the state transition it causes, not just memorize syntax.

## Mental model

```mermaid
flowchart LR
    W["Working files"] -->|stage| S["Staging area"]
    S -->|commit| L["Local Git history"]
    L -->|push| R["Remote GitHub repository"]
    R -->|fetch| L
```

For this lesson, identify which of these places the operation affects. Some GitHub-specific actions such as PR reviews happen on the hosting platform, while `git status`, `git add` and `git commit` work locally.

## Example

```bash
git remote -v
git remote add origin https://github.com/OWNER/REPO.git
```

**Walkthrough:** A remote is a named connection to another Git repository; origin is a common name. When running the example, check the current directory, branch and `git status` first. Record the output and determine whether a local commit, remote branch or GitHub collaboration object changed.

## Where it fits in real work

Use git remote -v to check that a personal project points to GitHub, not workplace GitLab.

## Common mistakes and trade-offs

**Watch for:** A remote URL determines where fetch/push communicate, not commit author identity.

When experimenting, use a disposable practice repository rather than your important notes or a company repository. Never include secrets or internal documents in demonstration commits.

## Exercise

**Task:** Explain fetch versus push directions.

**Check:** Describe the state of your working tree, staging area, local history and remote afterward; note which commands require internet access.

## Self-check

- [ ] I can explain what this operation changes.
- [ ] I can interpret its output or configuration.
- [ ] I completed the exercise on a practice repository.
- [ ] I can distinguish Git's local work from GitHub-hosted work.

## Related notes and sources

- [Chapter index](README.md)
- Previous: [[02_merge]]
- Next: [[04_clone_fetch_pull]]
- [Git documentation](https://git-scm.com/docs)
- [GitHub documentation](https://docs.github.com/)
