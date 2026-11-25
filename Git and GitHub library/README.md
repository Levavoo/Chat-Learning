---
type: library-index
kind: tool
technology: Git and GitHub
status: learning
tags: [git, github, navigation]
---

# Git and GitHub — Learning Library

Git is a version-control system. GitHub is a repository hosting and collaboration platform built around Git. This library starts with local commits, then moves to branches and remotes, review workflows and automation.

## Start here: the overall mental model

- [[00_big_picture/01_development_flow|Git Development — The Big Picture]] — diagrams showing local versus remote, parallel branches, commits, PRs, and merges.

## Learning path

1. [[01_fundamentals/README|Git fundamentals]] — snapshots, staging and history.
2. [[02_branches_and_remotes/README|Branches and remotes]] — integration and synchronization.
3. [[03_github_collaboration/README|GitHub collaboration]] — forks, PRs, issues and reviews.
4. [[04_automation_and_security/README|Automation and security]] — Actions, CI and permissions.

## Latest follow-up lesson

- [Branches, Commits, Hooks, and Pipeline Stages](04_automation_and_security/05_branches_commits_hooks_stages.md) — local hooks versus CI jobs, YAML entry points, runners, images, and a generic GitLab example.
- Next topic: OpenTofu, Terraform, and AWS; still to be studied.

## Repository exercise

Create an empty practice repository. Make two commits, create a branch, merge changes, add an appropriate `.gitignore`, then publish a harmless Markdown note to a new private GitHub repository. Open a documentation pull request from a feature branch.

## Git vs GitHub vs GitLab

- **Git** stores local commit graphs and branches.
- **GitHub** and **GitLab** are different remote hosting platforms offering collaboration and CI tools.
- Git authorship (`user.name`, `user.email`) is different from authentication for `git push`.
- `git config --local` changes settings only for the current repository.

## Resources

- [Pro Git book](https://git-scm.com/book/en/v2)
- [Git reference documentation](https://git-scm.com/docs)
- [GitHub skills](https://skills.github.com/)
