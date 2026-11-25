---
type: learnpaper
kind: service
technology: Cloud, IaC, and AWS
chapter: 4
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# S3, static website hosting, and DynamoDB

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../03-networking/03-dns-https-and-load-balancers.md) · [Next lesson](../04-storage-and-delivery/02-cache-cdn-cloudfront.md)

This is a **service** lesson: it explains managed AWS capabilities and how an application uses them.

> **In one sentence:** S3 stores and serves objects, while DynamoDB stores application records that you access through database operations.

## Learning objectives

Explain S3 hosting without a self-managed server and choose sensible locations for files and conversation records.

## Why it matters

“Both store data” does not mean these services are interchangeable. The operations your application needs determine which storage fits.

## Mental model

In **S3**, a bucket contains objects. An object has a key, bytes, and metadata. A key such as `faq/password-reset.pdf` identifies an object; the slashes create a useful naming hierarchy but are not ordinary filesystem directories.

In **DynamoDB**, tables contain items with attributes and keys. A table design might identify messages using a session ID and an ordered message identifier. Query patterns should influence key design. DynamoDB is a non-relational database; S3 is object storage.

| Need | Typical fit |
| --- | --- |
| Store a PDF, image, or built JavaScript file | S3 |
| Retrieve a particular conversation’s message records | DynamoDB |
| Execute Python business logic | Compute service, such as Lambda |

## Worked example: how S3 can host a website

Suppose the frontend build creates `index.html`, `app.js`, and `styles.css`.

1. Deployment uploads those files to S3.
2. AWS-operated systems receive requests for the objects.
3. They read and return the stored bytes.
4. The browser interprets HTML/CSS and runs JavaScript.
5. For an answer requiring business logic, JavaScript calls a separate backend API.

**There is a server delivering the files. You have bought that delivery capability as a managed service instead of maintaining its operating system and web-server process.**

Two configurations must be distinguished:

- **S3 website endpoint:** website-hosting behaviour such as index/error documents; does not support HTTPS directly and requires publicly readable website content.
- **Private S3 bucket behind CloudFront:** CloudFront uses the S3 REST endpoint as its origin. Origin Access Control (OAC), together with bucket policy configuration, permits CloudFront to fetch content while the bucket stays private.

The second design is commonly used for HTTPS delivery. OAC does not work with an S3 website endpoint treated as a custom origin. Browser navigation paths in a single-page application may also require deliberate routing/fallback configuration.

## Worked example: conversation storage

An illustrative DynamoDB item could contain:

```json
{
  "session_id": "demo-session",
  "message_order": "0001",
  "question": "How do I reset my password?",
  "answer": "Use the account recovery page."
}
```

This is an application-level illustration, not DynamoDB’s low-level wire format or a complete table definition. The backend must enforce that the requester may access the session; possession of a session ID alone should not grant access.

## Common mistakes

Uploading Python to S3 does not start Python. Bucket access rules do not replace application authorization. Storing all records in one JSON object may be possible, but concurrent updates and querying can become awkward.

## Practice

Place a logo, a backend handler, and conversation items in this design. Expected: S3; Lambda or another compute service; DynamoDB or another suitable database.

## Self-check

- [ ] I can explain who serves S3-hosted files.
- [ ] I can distinguish the two S3 hosting configurations.
- [ ] I can explain why object storage is not the same as a database.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [S3 objects](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingObjects.html)
- [S3 website hosting](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteHosting.html)
- [CloudFront access to S3](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [DynamoDB components](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
