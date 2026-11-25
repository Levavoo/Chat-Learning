---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 1
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Hosting: static files and dynamic responses

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../01-foundations/01-application-process-server.md) · [Next lesson](../01-foundations/03-vms-containers-serverless.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Hosting means making an application or its content available to users through a running delivery system.

## Learning objectives

Explain how a static website can be interactive, and identify when backend execution is required.

## Why it matters

A frontend build can be hosted very differently from a Python backend. This explains why a project may deploy one to S3 and the other to Lambda.

## Mental model

**Static delivery** returns stored content: HTML, CSS, JavaScript, images. The server does not need to execute your Python application to generate those files for each request.

**Dynamic processing** runs application logic for a request: checking who the user is, reading their history, calculating a result, or asking a language model for an answer.

“Static” describes how content is delivered, not whether the screen moves or responds to clicks. JavaScript downloaded as a static file can run in the browser and build an interactive interface.

## Worked example and walkthrough

Imagine the Helpdesk frontend is built into three files:

```text
index.html
app.js
styles.css
```

1. A hosting service sends these files to the browser.
2. The browser runs `app.js` and displays the chat form.
3. The user submits “How do I reset my password?”
4. JavaScript sends an HTTPS request to a backend API.
5. Backend code checks the request and returns an answer.
6. Browser JavaScript displays the answer.

There are two different kinds of work: **deliver existing files** and **compute a response**.

You could run both on one rented server. You could also use managed file delivery for the first and a function service for the second. Both arrangements still involve real computers somewhere.

A production website additionally needs an address users can resolve, valid HTTPS configuration, appropriate access controls, and an available hosting service. Copying a folder to an arbitrary machine does not provide all of these.

## Common mistakes

S3 can deliver a Python file as stored data; it does not execute that file as your backend. Likewise, an HTML file containing JavaScript does not give that browser code permission to access private AWS resources.

Server-side rendering is another design: a backend generates HTML. Do not assume every frontend framework deployment is purely static.

## Practice

Classify “serve logo.png”, “display a dropdown”, and “read a private conversation from a database”.

Expected: static file delivery; browser-side execution; authorized backend or authorized data-service access.

## Self-check

- [ ] I can explain how static hosting supports an interactive chat interface.
- [ ] I can identify which part needs backend computation.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [S3 website hosting](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
