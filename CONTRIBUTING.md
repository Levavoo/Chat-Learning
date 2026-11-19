# Knowledge Base Conventions

## Language and style

Write in clear **English**. Explain the idea first, then the details. Assume the reader is technically curious but may be new to infrastructure and production systems. Distinguish documented facts, analogies, assumptions, and personal observations. Prefer short sections, descriptive titles, and concrete examples over terminology lists.

## Technical stack

| Purpose | Default | Exceptions |
| --- | --- | --- |
| Notes and formatting | Markdown (`.md`) | None |
| Code examples | Python 3 | TypeScript for TS/JS frameworks, HTML/CSS for browser interfaces, shell for CLI usage, YAML for configuration, SQL for databases, etc. |
| Diagrams | Mermaid | Images only where a diagram cannot express the concept clearly |
| Knowledge graph | Obsidian `[[wikilinks]]` | Standard Markdown links for external resources |
| Version history | Git + GitHub | No need for build infrastructure just for notes |

## Note structure

Start from `Templates/Technology Note.md`. For very small concepts, a brief definition, example, related notes, and source may be sufficient. Do not force every note to contain every section.

Every note must declare a `kind` in YAML frontmatter to identify **what sort of thing** it documents: `command`, `technology`, `framework`, `library`, `architecture-style`, `architectural-pattern`, `protocol`, `service`, `tool`, `concept`, `language`, `platform`, or `other`. Choose the closest primary type; elaborate in the Classification section if it spans types. Do not confuse a CLI command with the underlying technology, or an architecture style with an implementation framework.

Examples: `git remote` → `command`; Docker → `technology`; FastAPI → `framework`; REST → `architecture-style`; AWS Lambda → `service`; HTTP → `protocol`.

A good note answers:
1. What is this?
2. Why would I use it?
3. How does it work?
4. Where does it sit in a larger system?
5. How can I recognize or try it in practice?
6. What is it connected to?

## Terminology intake

`Terms.md` is the intake backlog. All new terminology starts there as an unchecked plain term, even if a term was found in a source document with an existing definition. Research each term, then transfer it into `Glossary.md` **only when it is ready with a checked explanation and classification**. Mark or remove the backlog item after transfer. Do not duplicate existing glossary entries. Keep source documents separate from generalized notes, especially if a source contains confidential project details.

## Code and diagrams

- Use fenced code blocks with explicit language identifiers (e.g. `python`, `typescript`, `yaml`, `bash`, `mermaid`).
- Prefer minimal, self-contained, correct examples; state prerequisites for non-runnable snippets.
- Use Python unless another language is more faithful to the topic.
- Mermaid diagrams should show meaningful components or flows. Use simple labels and supplement them with prose.
- Never include real API keys, passwords, personal access tokens, or confidential endpoints.

## Obsidian and Git

- Keep one concept per note where practical.
- Use meaningful file names; avoid trailing spaces before `.md`.
- Preserve existing notes and links when reorganizing.
- Git history is for review, synchronization, and rollback; Markdown remains the source of truth.
- Keep workspace-local files out of version control using `.gitignore`.

## Source and review policy

Prefer official documentation for technology-specific claims and mark versions when behavior changes over time. Distinguish general explanations from verified repository-specific facts. AI-generated notes are drafts until reviewed. Prefer pull requests over automatic commits to `main`; never auto-merge generated documentation.
