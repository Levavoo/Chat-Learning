---
type: learnpaper
kind: concept
domain: version-control
technology: Git and GitHub
chapter: 00_big_picture
level: beginner
status: draft
tags: [git, github, branches, commits, workflow, visualization]
---

# Git Development — The Big Picture

> **Mental model:** Git tracks a history of commits and branches. Your computer has its own working files, staging area, and Git history; GitHub hosts a remote copy for collaboration.

**Read this note first** if you feel lost among branches, commits, pushes, pull requests, and merges.

## Learning objectives

- Distinguish local Git actions from remote GitHub actions.
- Read a commit graph showing several branches developing in parallel.
- Explain why a commit does not automatically appear on GitHub.
- Trace one feature from creating a branch to merging a pull request.

## 1. The two environments

**Local** means your computer: your files, staging area, commits, and local branches. **Remote** means a Git repository hosted elsewhere, for example on GitHub or GitLab.

\`\`\`mermaid
flowchart TB
    subgraph LOCAL["YOUR COMPUTER — LOCAL"]
        direction TB
        W["Working directory<br/>Edit files in VS Code"]
        S["Staging area<br/>Selected changes"]
        C["Local commit history<br/>Commit A → Commit B"]
        W -->|"git add"| S
        S -->|"git commit"| C
    end

    subgraph REMOTE["GITHUB — REMOTE"]
        direction TB
        RB["Remote feature branch"]
        PR["Pull request<br/>Review + optional CI checks"]
        MAIN["main branch"]
        RB -->|"Open PR"| PR
        PR -->|"Merge after review"| MAIN
    end

    C -->|"git push"| RB
    RB -.->|"git fetch: download refs and commits"| C
    MAIN -.->|"git pull: fetch + integrate"| C
\`\`\`

> **Critical distinction:** \`git commit\` records a snapshot in your **local** repository. \`git push\` shares local commits with a **remote** repository. \`git pull\` fetches and integrates remote changes; it is not the opposite of \`git push\` in every detail.

A branch may exist only locally, only on GitHub, or in both places. GitHub and GitLab both host Git repositories, but have different collaboration interfaces.

## 2. How to read a commit graph

In this diagram, each commit is one saved snapshot. Branches are movable labels pointing at commits; they are **not** copies of the entire project.

\`\`\`mermaid
gitGraph
    commit id: "A: initial"
    commit id: "B: stable"
    branch feature-api
    checkout feature-api
    commit id: "C: endpoint"
    commit id: "D: tests"
    checkout main
    branch feature-ui
    checkout feature-ui
    commit id: "E: page"
    commit id: "F: styles"
    checkout main
    merge feature-api id: "M1: API merged"
    branch bugfix-login
    checkout bugfix-login
    commit id: "G: fix"
    checkout main
    merge feature-ui id: "M2: UI merged"
    merge bugfix-login id: "M3: bugfix merged"
\`\`\`

**Reading it:**

1. Work starts on \`main\` at commits A and B.
2. Developer 1 creates \`feature-api\` and records commits C and D.
3. Developer 2 creates \`feature-ui\` and records commits E and F. The work is independent.
4. Both changes are integrated into \`main\` at different times.
5. A bugfix can start from the then-current \`main\` and be merged later.

**Important:** The graph is illustrative. Git can integrate changes by merge commits, fast-forward merges, rebases, or squash merges. A merged pull request does not always correspond to exactly one special merge commit, and the branch name may be deleted after integration while its commits remain.

### Why main can move while you work

Suppose your feature starts at commit B, but another developer merges something into \`main\` before you finish. Your feature branch does **not** automatically gain those new commits. You might have to update it by merging or rebasing from \`main\` before integration.

## 3. One feature, from idea to main

\`\`\`mermaid
flowchart TD
    A["Start with latest local main"] --> B["Create a feature branch"]
    B --> C["Edit and test files"]
    C --> D["git add → git commit"]
    D --> E["git push feature branch"]
    E --> F["Open GitHub pull request"]
    F --> G{"Review / CI acceptable?"}
    G -->|"No: make corrections"| C
    G -->|"Yes"| H["Merge into remote main"]
    H --> I["Switch local branch to main"]
    I --> J["git pull to update local main"]
\`\`\`

Note that continuous integration (CI) is optional and runs only if configured. Review policies also depend on the repository.

## 4. Follow a concrete example

Imagine adding a new Markdown lesson to your personal knowledge base.

**Start from an up-to-date main:**

\`\`\`powershell
git switch main
git pull --ff-only origin main
git switch -c docs/git-lesson
\`\`\`

The first two commands select and update your local \`main\`; the third creates and switches to a separate local branch.

**Edit the files in VS Code, then record two local commits:**

\`\`\`powershell
git add .
git diff --cached
git commit -m "docs: add Git lesson"

# Make another edit in VS Code
git add .
git commit -m "docs: add practical examples"
\`\`\`

**Inspect what happened before uploading:**

\`\`\`powershell
git status
git log --oneline --graph --decorate -6
\`\`\`

You now have two new local commits on \`docs/git-lesson\`, not on local \`main\`.

**Push the feature branch to GitHub:**

\`\`\`powershell
git push -u origin docs/git-lesson
\`\`\`

The \`-u\` flag configures the upstream tracking relationship. On GitHub, open a pull request with **base = main** and **compare = docs/git-lesson**. Review the diff, run any configured checks, and merge if acceptable.

**After merging on GitHub, update the computer:**

\`\`\`powershell
git switch main
git pull --ff-only origin main
\`\`\`

Your local \`main\` now reflects the merged remote history, assuming the pull can fast-forward.

## 5. Commands and where they act

| Action | Local or remote? | What actually changes? |
| --- | --- | --- |
| Edit a file | Local | Working directory |
| \`git add\` | Local | Staging area |
| \`git commit\` | Local | Git history and current branch pointer |
| \`git switch -c\` | Local | Creates/switches a local branch |
| \`git push\` | Both | Uploads objects and updates a remote ref |
| Open a PR | GitHub | Collaboration/review record |
| Merge a PR | GitHub | Updates remote target branch |
| \`git fetch\` | Both | Downloads objects and updates remote-tracking refs locally |
| \`git pull\` | Both | Fetches then integrates into your local branch |

## 6. Common misunderstandings

- **"Commit means saved to GitHub."** No: commit is local. Push is the sharing operation.
- **"Branches are different copies of the whole repository."** No: they are pointers within a shared commit graph.
- **"Pull request automatically merges the work."** No: it proposes integration; merge is a separate step.
- **"My local main changes when a PR is merged."** No: update your local repository with fetch/pull.
- **"A branch contains only my code."** It also shares history with its starting point and may integrate other work.
- **"Deleting a file erases it from Git history."** No: previously committed content may remain reachable in history.

## 7. Practice: draw your own history

In a disposable repository, create an initial commit and two feature branches.

1. Make two commits on \`feature-a\` and one on \`feature-b\`.
2. Merge one feature into \`main\`, then the other.
3. Inspect the graph:

\`\`\`powershell
git log --oneline --graph --decorate --all
\`\`\`

4. Sketch which commits belong to each line of history, which branch labels moved, and whether the merge produced an extra commit.

**Self-check**

- [ ] I can explain why a commit is local but a PR is hosted on GitHub.
- [ ] I can explain a branch and a commit without confusing the two.
- [ ] I can read the split and join points in a commit graph.
- [ ] I can trace edits → staging → commits → push → PR → merge → pull.

## Continue learning

- [[Git and GitHub library/01_fundamentals/01_git_vs_github|Git versus GitHub]]
- [[Git and GitHub library/01_fundamentals/04_git_add_commit|Staging and commits]]
- [[Git and GitHub library/02_branches_and_remotes/01_branches|Branches]]
- [[Git and GitHub library/02_branches_and_remotes/02_merge|Merging]]
- [[Git and GitHub library/02_branches_and_remotes/04_clone_fetch_pull|Fetch versus pull]]
- [[Git and GitHub library/03_github_collaboration/03_pull_requests|Pull requests]]
- [Git and GitHub library index](../README.md)
- [Pro Git — Git Branching](https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell)
- [GitHub Docs — About pull requests](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests)
