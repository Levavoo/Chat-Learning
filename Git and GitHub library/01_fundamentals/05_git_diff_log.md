---
type: learnpaper
kind: tool
domain: version-control
technology: Git and GitHub
chapter: 01_fundamentals
level: beginner
status: draft
tags: [git, github, fundamentals]
---

# Inspect Differences and History

> **In one sentence:** git diff displays file changes and git log shows recorded commits.

## Learning objectives

- Explain the role of this concept in version control or GitHub collaboration.
- Use or interpret the example below and understand what changes locally versus remotely.
- Identify a common mistake before making it in a real repository.

## Why it matters

git diff displays file changes and git log shows recorded commits. It helps make changes traceable and collaboration safer. The goal is to understand both the command and the state transition it causes, not just memorize syntax.

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
git diff
git diff --cached
git log --oneline --graph --decorate
```

**Walkthrough:** git diff displays file changes and git log shows recorded commits. When running the example, check the current directory, branch and `git status` first. Record the output and determine whether a local commit, remote branch or GitHub collaboration object changed.

## Where it fits in real work

A clean working tree can still have history and branches.

## Common mistakes and trade-offs

**Watch for:** Plain git diff shows unstaged differences; --cached shows staged differences.

When experimenting, use a disposable practice repository rather than your important notes or a company repository. Never include secrets or internal documents in demonstration commits.

## Exercise

**Task:** Compare a staged edit with the latest committed version.

**Check:** Describe the state of your working tree, staging area, local history and remote afterward; note which commands require internet access.

## Self-check

- [ ] I can explain what this operation changes.
- [ ] I can interpret its output or configuration.
- [ ] I completed the exercise on a practice repository.
- [ ] I can distinguish Git's local work from GitHub-hosted work.

## Related notes and sources

- [Chapter index](README.md)
- Previous: [[04_git_add_commit]]
- Next: [[06_gitignore]]
- [Git documentation](https://git-scm.com/docs)
- [GitHub documentation](https://docs.github.com/)
