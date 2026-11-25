---
type: learnpaper
kind: concept
technology: Cloud, IaC, and AWS
chapter: 3
level: beginner
status: draft
tags: [cloud, aws, learning]
---

# VPCs, subnets, routes, and gateways

[Chapter index](README.md) · [Library index](../README.md) · [Previous lesson](../02-architecture/02-mainframes-and-applications.md) · [Next lesson](../03-networking/02-inbound-outbound-and-filters.md)

This is a **concept** lesson: it connects ideas and responsibilities rather than teaching one command.

> **In one sentence:** A network needs a path to a destination as well as rules allowing traffic to use that path.

## Learning objectives

Describe a VPC and subnet, and distinguish Internet, NAT, and virtual private gateways.

## Why it matters

A deployment can succeed while the application cannot reach a dependency. Permissions alone cannot create a missing network route.

## Mental model

An **IP address** identifies a network destination. A **port** identifies an endpoint on that destination, such as TCP port 443 for HTTPS.

A **VPC** is a logically isolated network in AWS. You divide its address space into **subnets**; an AWS subnet belongs to one Availability Zone. A **route table** tells traffic which next destination to use based on its destination address.

| Component | Typical purpose |
| --- | --- |
| Internet gateway | Connect a VPC to the Internet |
| Public NAT gateway | Allow private resources to initiate IPv4 Internet connections through translated addresses |
| Virtual private gateway (VGW) | AWS-side endpoint for a VPN connection to a VPC |

A public subnet has a route to an Internet gateway. For direct IPv4 Internet connectivity, a VM also needs suitable public addressing and traffic rules. A private subnet has no direct route to an Internet gateway.

## Worked example and walkthrough

A private backend needs to download a public package:

1. Its destination address is outside the VPC.
2. The private subnet’s route table sends that traffic to a public NAT gateway.
3. The NAT gateway is in a public subnet and uses the Internet gateway.
4. Response traffic returns through the established translation.

This does not make the backend directly reachable for unsolicited Internet requests.

For access to an office network, a site-to-site VPN can instead connect the office gateway to a VGW. Both sides need suitable routes and controls. “VPG gateway” is often a mistaken name for **VGW**.

Some AWS-service access can use private service endpoints instead of Internet routing; treat this as a later topic.

## Common mistakes

Putting a function or VM in a “public subnet” is not a universal Internet-access switch. In particular, attaching Lambda to a public subnet does not give its execution environment a public IP address.

Not every AWS service sits inside your VPC. S3 and DynamoDB are managed services accessed through their endpoints.

## Practice

The firewall allows HTTPS, but there is no route to the destination. Will the request work? Expected: no. Both reachability and permission matter.

## Self-check

- [ ] I can distinguish a route from a traffic rule.
- [ ] I can explain why NAT and a VPN gateway solve different problems.

## Related notes and sources

- [[Terms]] and [[Glossary]] for short definitions.
- [Chapter index](README.md)
- [Library index](../README.md)
- [VPC route tables](https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Route_Tables.html)
- [NAT gateways](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html)
- [Site-to-site VPN](https://docs.aws.amazon.com/vpn/latest/s2svpn/how_it_works.html)
- [Lambda Internet access in a VPC](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc-internet.html)

Documentation consulted 2026-11-25. Examples are educational drafts; service features and tool behaviour can change.
