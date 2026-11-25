---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 1
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Application, process, server, and infrastructure

[Chapter index](README.md) · [Library index](../README.md) · [Next lesson](../01-foundations/02-hosting-static-dynamic.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** An application is the software that does the work; infrastructure supplies the computing, storage, and connections it needs.

## Learning objectives

Explain what runs when you start a program, and distinguish an application from the machine hosting it.

## Why it matters

“The backend is down” can mean broken code, a stopped process, missing permissions, or an unreachable machine. These are different places to investigate.

## Mental model

A Python file sitting on disk is not doing anything. Starting Python loads instructions into memory and creates a **process**: a running instance of a program. The operating system gives that process CPU time and access to memory, files, and network connections.

**Server** has two common meanings:

- A computer or virtual machine supplying resources.
- A program that listens for requests and responds.

One computer can run several server programs. An application can also span many computers. Infrastructure includes more than servers: networks, storage, databases, identity configuration, and monitoring can all support the application.

Our fictional **Helpdesk** application lets a person ask questions about an organisation’s public FAQ. Its frontend displays messages; its backend checks requests and assembles answers. AWS is a provider of services we could use to run these parts.

## Worked example and walkthrough

Illustrative local example; Python 3 must be installed. In a folder containing a harmless `index.html`, run:

```bash
python -m http.server 8000 --bind 127.0.0.1
```

1. Your shell starts a Python process.
2. That process listens on local port 8000.
3. Opening `http://127.0.0.1:8000` in your browser sends a request to it.
4. Python reads the file and returns its bytes.
5. Pressing Ctrl+C stops the process; the file remains, but the server stops answering.

Here, your laptop is the host, Python supplies the server program, and the HTML is the content. This simple server is for local learning, not production hosting.

## Common mistakes

A repository contains source files; pushing them does not automatically run a process. A pipeline or another deployment mechanism must prepare and install the runnable result.

“Server” also does not necessarily mean a large physical box assigned only to one app.

## Practice

Explain what remains after stopping the command. Expected answer: the source/content files remain; the running server process does not.

## Self-check

- [ ] I can distinguish a file, a process, and its host.
- [ ] I can name two infrastructure components besides a server.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [Python HTTP server](https://docs.python.org/3/library/http.server.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
