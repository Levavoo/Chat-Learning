# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## infrastructure-3.53.0 - 2026-11-20
#### Features
- (**cdk**) Token-Alarm gpt-oss in Prod, Runbook Reaktion (#989) - (e731b4e) - Klaus Müller

- - -

## infrastructure-3.52.0 - 2026-11-20
#### Features
- (**cdk**) WAF-Aktion je Regelpaket und Web ACL statt wafRuleAction - (088fa6f) - Klaus Müller

- - -

## infrastructure-3.51.0 - 2026-11-16
#### Features
- (**cdk**) langfuseKeyRotatedAt erzwingt Kaltstart nach Schlüsseltausch - (f2a7186) - Klaus Müller

- - -

## infrastructure-3.50.1 - 2026-11-13
#### Bug Fixes
- (**broschures**) Broschueren 300, 501, 509 und 1 weitere aktualisieren - (fefaf8d) - wissensbasis-mr-bot
#### Miscellaneous Chores
- (**cert-notifier**) remove migrated stack - (7222578) - Huy Le Duc

- - -

## infrastructure-3.50.0 - 2026-10-26
#### Features
- (**chat**) X-Renate-User-Id override for synthetic eval traffic - (328eb05) - Huy Le Duc

- - -

## infrastructure-3.49.1 - 2026-10-23
#### Bug Fixes
- (**broschures**) publish 23 october 2026 corpus - (c72eedb) - Elias Büchner
#### Refactoring
- (**dev**) release Langfuse from state after extraction into renate/langfuse - (ea0b4de) - Huy Le Duc
- retire Langfuse Packer builder - (46ed3ab) - Huy Le Duc
- retire untrusted Langfuse prod stub - (1a8b088) - Huy Le Duc

- - -

## infrastructure-3.49.0 - 2026-10-20
#### Features
- (**langfuse**) cut DEV over to v4 events_only (#901) - (51ad818) - Huy Le Duc

- - -

## infrastructure-3.48.0 - 2026-10-19
#### Features
- (**langfuse**) resize DEV host to t3.xlarge for v4 backfill (#900) - (49827f5) - Huy Le Duc

- - -

## infrastructure-3.47.0 - 2026-10-19
#### Features
- (**langfuse**) enable DEV v4 historic backfill (#900) - (7d49b69) - Huy Le Duc

- - -

## infrastructure-3.46.0 - 2026-10-19
#### Features
- (**langfuse**) raise DEV data EBS to 200 GiB for v4 backfill (#900) - (330b2fc) - Huy Le Duc

- - -

## infrastructure-3.45.0 - 2026-10-16
#### Features
- (**langfuse**) bump DEV module default to 4.61.0 - (ab89a3e) - Huy Le Duc

- - -

## infrastructure-3.44.1 - 2026-10-14
#### Bug Fixes
- (**terraform-dev**) bump review-frontend module to 0.1.2 - (e20b980) - Huy Le Duc

- - -

## infrastructure-3.44.0 - 2026-10-14
#### Features
- (**terraform-dev**) consume review-frontend 0.1.x from module registry - (9c6e694) - Huy Le Duc

- - -

## infrastructure-3.43.6 - 2026-10-12
#### Bug Fixes
- (**langfuse**) vertical-scale DEV host to t3.large (#906) - (eeaa30d) - Huy Le Duc

- - -

## infrastructure-3.43.5 - 2026-10-09
#### Bug Fixes
- (**langfuse**) restore dual write mode after UI regression - (be5b96d) - Huy Le Duc

- - -

## infrastructure-3.43.4 - 2026-10-09
#### Bug Fixes
- (**langfuse**) couple OTel behaviour to events_only write mode - (81b1b38) - Huy Le Duc

- - -

## infrastructure-3.43.3 - 2026-10-09
#### Bug Fixes
- (**langfuse**) flip DEV to events_only ingestion mode - (71b27de) - Huy Le Duc
#### Miscellaneous Chores
- (**infra**) upgrade DEV Langfuse to v4 (dual mode) - (89f83b8) - Huy Le Duc

- - -

## infrastructure-3.43.2 - 2026-10-05
#### Bug Fixes
- (**broschures**) publish 5 october 2026 corpus - (b816abf) - Elias Büchner

- - -

## infrastructure-3.43.1 - 2026-09-21
#### Bug Fixes
- (**broschures**) publish 21 september 2026 corpus - (530cc36) - Elias Büchner

- - -

## infrastructure-3.43.0 - 2026-09-21
#### Features
- (**cdk**) enable budget pacing for prod (#579) - (a8b9e90) - Tobi Pfeiffer

- - -

## infrastructure-3.42.3 - 2026-09-15
#### Bug Fixes
- (**retrieval**) skip selector rewrite when candidate matches active - (af7dfef) - Huy Le Duc
#### Miscellaneous Chores
- (**retention**) decommission scheduled retrieval-retention (narrow scope) - (524bb7a) - Huy Le Duc

- - -

## infrastructure-3.42.2 - 2026-09-10
#### Bug Fixes
- (**broschures**) publish September 2026 corpus - (81c3fd5) - elias.buechner

- - -

## infrastructure-3.42.1 - 2026-09-10
#### Bug Fixes
- (**broschures**) restore published corpus before September update - (b874226) - elias.buechner

- - -

## infrastructure-3.42.0 - 2026-08-27
#### Features
- (**infra**) add prod certificate expiry email notifier (#577) - (192a78f) - Klaus Müller

- - -

## infrastructure-3.41.1 - 2026-08-20
#### Bug Fixes
- (**deploy**) enable-health retrieval - (8221b2c) - Huy Le Duc

- - -

## infrastructure-3.41.0 - 2026-08-19
#### Features
- (**langfuse**) enable trace content export by default in all stages (#774) - (85fab22) - Klaus Müller

- - -

## infrastructure-3.40.0 - 2026-08-19
#### Features
- (**langfuse**) allow Prod to use shared Dev endpoint transitionally (#773) - (20e4dbc) - Klaus Müller
#### Miscellaneous Chores
- (**ci**) instrument release-retention with structured metrics logging - (4ae6f02) - Tobi Pfeiffer

- - -

## infrastructure-3.39.0 - 2026-08-19
#### Features
- (**langfuse**) harden Prod platform and edge security (#749) - (05cb267) - Klaus Müller

- - -

## infrastructure-3.38.2 - 2026-08-19
#### Bug Fixes
- (**broschures**) update broschures 2026 - (e10528f) - Felix

- - -

## infrastructure-3.38.1 - 2026-08-19
#### Bug Fixes
- (**langfuse**) protect content in telemetry (#750) - (21086b7) - Klaus Müller

- - -

## infrastructure-3.38.0 - 2026-08-18
#### Features
- (**langfuse**) prepare Prod domain, TLS, and Authentik (#748) - (86e16c9) - Klaus Müller

- - -

## infrastructure-3.37.2 - 2026-08-18
#### Bug Fixes
- (**ses**) route brochure alerts to official mailboxes - (14d4ce9) - chewbacca89

- - -

## infrastructure-3.37.1 - 2026-08-18
#### Bug Fixes
- (**langfuse**) prevent unintended Dev host replacement - (2e3e4f6) - Klaus Müller

- - -

## infrastructure-3.37.0 - 2026-08-17
#### Features
- (**ci**) modularize QA retrieval orchestration helpers - (2f0cca2) - Tobi Pfeiffer

- - -

## infrastructure-3.36.0 - 2026-08-17
#### Features
- (**langfuse**) reference prod runtime secrets (#751) - (98b571a) - Klaus Müller

- - -

## infrastructure-3.35.1 - 2026-08-17
#### Bug Fixes
- (**cdk**) scope execute-api to dev CSP connect-src for review deploys - (a1ab780) - Tobi Pfeiffer

- - -

## infrastructure-3.35.0 - 2026-08-14
#### Features
- (**langfuse**) add prod foundation (#747) - (d266d00) - Klaus Müller

- - -

## infrastructure-3.34.3 - 2026-08-14
#### Bug Fixes
- (**ci**) paginate chatbot Lambda enumeration (#671) - (853a8db) - Felix

- - -

## infrastructure-3.34.2 - 2026-08-14
#### Bug Fixes
- (**#724**) remove skipBudgetAlerts workaround from prod - (b632cf3) - Huy Le Duc
#### Miscellaneous Chores
- (**terraform**) retrigger tofu-plan:preprod under new CI (#746) - (4aa8790) - Huy Le Duc

- - -

## infrastructure-3.34.1 - 2026-08-12
#### Bug Fixes
- (**acm-expiry-notifier**) attach org permissions boundary to forwarder role - (8d6480f) - Huy Le Duc

- - -

## infrastructure-3.34.0 - 2026-08-12
#### Features
- (**terraform**) preprod cert-expiry notifier via aws.acm EventBridge event (#746) - (10ed167) - Huy Le Duc

- - -

## infrastructure-3.33.1 - 2026-08-11
#### Bug Fixes
- (**cdk**) retain conversations for 180 days - (dc05cd0) - Klaus Müller

- - -

## infrastructure-3.33.0 - 2026-08-11
#### Features
- (**cdk**) prepare prod DNS alias records - (befcd8c) - chewbacca89

- - -

## infrastructure-3.32.0 - 2026-08-11
#### Features
- (**retrieval**) prepare prod cutover controls (#671) - (3e34f86) - Felix

- - -

## infrastructure-3.31.3 - 2026-08-11
#### Bug Fixes
- (**etl**) preserve Merkblatt PDF content during extraction - (29f13d3) - Felix

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).