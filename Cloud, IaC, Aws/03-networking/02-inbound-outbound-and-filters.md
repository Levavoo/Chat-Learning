---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 3
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# Inbound, outbound, security groups, and network ACLs

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../03-networking/01-vpc-subnets-routes-gateways.md) · [Next lesson](../03-networking/03-dns-https-and-load-balancers.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** Traffic direction depends on your viewpoint, while stateful filtering remembers connections and stateless filtering evaluates packets independently.

## Learning objectives

Trace a request and response through traffic rules without confusing connection state with application data.

## Why it matters

“Allow HTTPS” can be incomplete. You need to know which resource, direction, source, destination, and return path are involved.

## Mental model

Relative to the backend, a request arriving at it is **inbound**. A request it initiates to another service is **outbound**. The same packet can be outbound from one component and inbound to another.

| Feature | Security group | Network ACL |
| --- | --- | --- |
| Scope | Associated resources/network interfaces | Subnet boundary |
| Rules | Allow rules | Allow and deny rules |
| Connection tracking | Stateful | Stateless |
| Evaluation | Applicable allows combine | Numbered rules; first matching rule wins |
| Return traffic | Automatically allowed for tracked allowed connections | Must be allowed by rules in the return direction |

An **ACL** is a general access-control-list concept. An AWS network ACL is one particular network mechanism.

## Worked example and walkthrough

Suppose a client connects from source port 51000 to a backend’s HTTPS port 443.

1. The request is inbound to the backend, destination port 443.
2. A suitable security-group inbound rule permits it.
3. The reply goes to the client’s port 51000.
4. Security-group connection tracking recognises the response.
5. A stateless network ACL also needs appropriate outbound rules for that response.

Client ports are typically chosen from an operating-system-dependent ephemeral range. Do not copy one example port into a production rule and assume every connection will work.

## Connection state versus application state

A stateful firewall remembers a permitted network connection. A stateful application might remember a shopping basket or conversation.

A backend can keep conversation history in DynamoDB while running instances that do not depend on their own local memory. Such instances are often described as stateless application instances, even though the overall system stores data.

## Common mistakes

A security group does not grant permission to read an S3 object. IAM and resource policies handle that service authorization. Conversely, an IAM allow cannot repair a blocked network path.

An explicit deny in a network ACL is different from the absence of an allow in a security group.

## Practice

A backend makes an allowed outbound request. Must its security group separately allow the matching response as a new inbound connection? Expected: no, for tracked response traffic. A stateless ACL still needs the return path allowed.

## Self-check

- [ ] I can explain direction from a named component’s viewpoint.
- [ ] I can distinguish connection tracking from stored conversation history.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [Security groups](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html)
- [Network ACLs](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
