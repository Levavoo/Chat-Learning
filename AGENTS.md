# Instructions for AI Assistants and Codex

This repository is a personal Obsidian knowledge base about programming, infrastructure, DevOps, cloud, backend systems, AI and chatbot technology.

## Mandatory defaults

- Write all new or revised notes in **English**.
- Use **Markdown** for all documentation.
- Use **Python 3** for language-independent programming examples.
- Use **TypeScript**, **HTML**, **CSS**, **YAML**, **SQL**, shell, or other languages when they are necessary to represent the actual technology accurately.
- Use **Mermaid** for diagrams; keep diagrams focused, correct, and accompanied by explanatory text.
- Classify every new note with a `kind` in YAML frontmatter (e.g. command, technology, framework, library, architecture-style, architectural-pattern, protocol, service, tool, concept, language, platform, other); explain the classification in the note.
- Follow `CONTRIBUTING.md`; use `Templates/Technology Note.md` as the starting point for substantive technology notes.
- Write for a beginner transitioning into production software and chatbot infrastructure: start with the simplest mental model before adding implementation details.

## Term intake workflow

- Add newly encountered technical vocabulary to `Terms.md` first; do not add an unexplained term directly to `Glossary.md`.
- When a term has a verified, beginner-friendly English definition and a clear classification, move it to `Glossary.md` and mark it complete or remove it from the term backlog. Avoid duplicates.
- Use a dedicated technology note for topics that need examples, implementation details, or Mermaid diagrams.
- Never transfer proprietary source material or project-specific architecture into public learning notes.

## Accuracy and safety

- Check existing notes before creating duplicates; add bidirectional relationships where useful.
- Do not assume specifics about a workplace system, private monorepo, or deployment without evidence.
- Do not insert company-internal content, secrets, credentials, or identifying system details.
- Do not fabricate citations, commands, testing results, or API behavior; acknowledge uncertain facts.
- Prefer official documentation, add links under Sources, and label version-sensitive information.
- Preserve existing authored material unless specifically asked to refactor it.

## Changes

- Propose limited, reviewable changes on a separate branch / pull request.
- Do not automatically merge into `main`.
- Avoid introducing dependencies, CI services, scripts, or complicated tooling without a clear need.
- For generated examples, favor minimal self-contained code; specify whether it has been run or is illustrative.
