# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## frontend-3.39.0 - 2026-11-22
#### Features
- (**chat**) Konversationslimit 20 Nachrichten (#992) - (5ed0f16) - Klaus Müller

- - -

## frontend-3.38.2 - 2026-11-02
#### Bug Fixes
- (**Ticket-935**) added changes to scenarios and comment field - (1d10b55) - Lucy

- - -

## frontend-3.38.1 - 2026-11-02
#### Bug Fixes
- (**feedback**) use 0 for the free test mode in used_scenario - (9ddc1d8) - Ilona Nietosvaara
#### Miscellaneous Chores
- (**review**) keep review rows for 21 days in conversation.py - (92e8a8a) - Ilona Nietosvaara

- - -

## frontend-3.38.0 - 2026-10-28
#### Features
- (**feedback**) validate ratings and store dialog and final ratings on their own rows - (1696526) - Ilona Nietosvaara

- - -

## frontend-3.37.0 - 2026-10-27
#### Features
- (**Ticket-904**) Refactoring per turn feedback - (90c036a) - Lucy

- - -

## frontend-3.36.0 - 2026-10-26
#### Features
- (**chat**) X-Renate-User-Id override for synthetic eval traffic - (328eb05) - Huy Le Duc

- - -

## frontend-3.35.0 - 2026-10-23
#### Features
- (**chat**) complete langfuse v4 Experiments contract (item baggage + rootSpanId) - (6da5fd3) - Huy Le Duc

- - -

## frontend-3.34.0 - 2026-10-21
#### Features
- (**chat**) expose all_sources and section/domain fields under X-Renate-Eval-Mode - (ceb24e7) - Huy Le Duc

- - -

## frontend-3.33.0 - 2026-10-19
#### Features
- (**backend**) sync Langfuse Score Configs from FEEDBACK_SCORE_SCHEMA (#941) - (8055d90) - Huy Le Duc

- - -

## frontend-3.32.5 - 2026-10-19
#### Bug Fixes
- (**frontend**) regenerate api.generated.ts for English feedback literals - (05c16bb) - Huy Le Duc

- - -

## frontend-3.32.4 - 2026-10-19
#### Bug Fixes
- (**backend**) handling_corrections → langfuse score, enforce rating literals (#909) - (41e80a9) - Huy Le Duc

- - -

## frontend-3.32.3 - 2026-10-14
#### Bug Fixes
- (**frontend**) use prod feedback constants in QA build - (2c76c5c) - Tobi Pfeiffer

- - -

## frontend-3.32.2 - 2026-10-12
#### Bug Fixes
- (**Ticket-874**) adjusted internal feedback and openApi - (5d3122e) - lucy.stepanenko.extern

- - -

## frontend-3.32.1 - 2026-10-12
#### Bug Fixes
- (**feedback**) emit user.helpfulness CATEGORICAL score for external 3-button rating (#905) - (c4139be) - Huy Le Duc

- - -

## frontend-3.32.0 - 2026-10-07
#### Features
- (**chat**) expose trace_id in /api/chat response - (e3ad25b) - Huy Le Duc

- - -

## frontend-3.31.20 - 2026-09-28
#### Bug Fixes
- (**Ticket-870**) replaced internal constant for prod build - (56fdb6c) - Lucy

- - -

## frontend-3.31.19 - 2026-09-28
#### Bug Fixes
- (**#871**) strip S3 URI from chunk storage, restore stable document grouping - (636459e) - Tobi Pfeiffer

- - -

## frontend-3.31.18 - 2026-09-21
#### Bug Fixes
- (**Ticket-839**) adjusted model - (b0a06f4) - Lucy

- - -

## frontend-3.31.17 - 2026-09-18
#### Bug Fixes
- (**Ticket-842**) moved new styles for last design system into assets - (eed60e9) - lucy.stepanenko.extern

- - -

## frontend-3.31.16 - 2026-09-17
#### Bug Fixes
- (**Ticket-841**) adjusted css - (fb0db4f) - lucy.stepanenko.extern

- - -

## frontend-3.31.15 - 2026-09-15
#### Bug Fixes
- (**frontend**) added new shortlinks to frontend - (a269a4e) - pfeiffer, tobi

- - -

## frontend-3.31.14 - 2026-09-15
#### Bug Fixes
- (**frontend**) correct feedback button URL (#830) - (aa9994b) - Huy Le Duc

- - -

## frontend-3.31.13 - 2026-09-14
#### Bug Fixes
- (**frontend**) keep REVIEW badge off in QA by default - (90c7455) - Tobi Pfeiffer

- - -

## frontend-3.31.12 - 2026-09-14
#### Bug Fixes
- (**frontend**) make REVIEW badge visibility configurable via env var - (c978dcd) - Tobi Pfeiffer

- - -

## frontend-3.31.11 - 2026-08-28
#### Bug Fixes
- (**frontend**) make deployed smoke config-aware - (de2378d) - Elias Büchner
#### Continuous Integration
- (**frontend**) add post-deploy browser smoke - (55cae7e) - Elias Büchner
- (**frontend**) add production browser smoke test - (49e673d) - elias.buechner

- - -

## frontend-3.31.10 - 2026-08-19
#### Bug Fixes
- (**frontend**) handle optional IdP environment variables - (056110a) - felixgeyer

- - -

## frontend-3.31.9 - 2026-08-18
#### Bug Fixes
- (**TP3DI-545**) Refactoring enviroment imports - (b7812a1) - Lucy

- - -

## frontend-3.31.8 - 2026-08-17
#### Bug Fixes
- (**analytics**) reconcile topic taxonomy with live domain classification - (9025810) - Aphrodite Arwanitidou

- - -

## frontend-3.31.7 - 2026-08-17
#### Bug Fixes
- (**cdk**) scope execute-api to dev CSP connect-src for review deploys - (a1ab780) - Tobi Pfeiffer

- - -

## frontend-3.31.6 - 2026-08-17
#### Bug Fixes
- (**frontend**) Updaiting dependencies to reduce vulnerabilities - (14cbded) - Lucy

- - -

## frontend-3.31.5 - 2026-08-14
#### Bug Fixes
- (**frontend**) updated links - (34e9264) - lucy.stepanenko.extern

- - -

## frontend-3.31.4 - 2026-08-13
#### Bug Fixes
- (**frontend**) Content for consent page - (c27d74e) - Lucy

- - -

## frontend-3.31.3 - 2026-08-12
#### Bug Fixes
- improve dashboard labels and topic classification - (c33766f) - Aphrodite Arwanitidou

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).