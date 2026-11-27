# Changelog
All notable changes to this project will be documented in this file. See [conventional commits](https://www.conventionalcommits.org/) for commit guidelines.

- - -
## backend-3.46.0 - 2026-11-22
#### Features
- (**chat**) Konversationslimit 20 Nachrichten (#992) - (5ed0f16) - Klaus Müller

- - -

## backend-3.45.0 - 2026-11-20
#### Features
- (**etl**) vier weitere FAQ-Quellen und Ranking-Einträge (#1002) - (e207b32) - Elias Büchner

- - -

## backend-3.44.0 - 2026-11-20
#### Features
- (**etl**) FAQ-Quelle Beiträge Pflegeversicherung (#987) - (af90a97) - Elias Büchner
#### Documentation
- (**scripts**) LangFuse-Schlüsseltausch mit Rotationsskript und Runbook - (bbc4cde) - Klaus Müller

- - -

## backend-3.43.3 - 2026-11-02
#### Bug Fixes
- (**Ticket-935**) added changes to scenarios and comment field - (1d10b55) - Lucy

- - -

## backend-3.43.2 - 2026-11-02
#### Bug Fixes
- (**feedback**) use 0 for the free test mode in used_scenario - (9ddc1d8) - Ilona Nietosvaara

- - -

## backend-3.43.1 - 2026-11-02
#### Bug Fixes
- (**sync**) use int literal arg as Langfuse score value - (b6956dd) - Huy Le Duc
#### Miscellaneous Chores
- (**review**) keep review rows for 21 days in conversation.py - (92e8a8a) - Ilona Nietosvaara

- - -

## backend-3.43.0 - 2026-10-28
#### Features
- (**feedback**) validate ratings and store dialog and final ratings on their own rows - (1696526) - Ilona Nietosvaara

- - -

## backend-3.42.0 - 2026-10-27
#### Features
- (**Ticket-904**) Refactoring per turn feedback - (90c036a) - Lucy

- - -

## backend-3.41.0 - 2026-10-26
#### Features
- (**chat**) X-Renate-User-Id override for synthetic eval traffic - (328eb05) - Huy Le Duc

- - -

## backend-3.40.0 - 2026-10-23
#### Features
- (**chat**) complete langfuse v4 Experiments contract (item baggage + rootSpanId) - (6da5fd3) - Huy Le Duc

- - -

## backend-3.39.0 - 2026-10-23
#### Features
- (**chat**) emit langfuse v4 experiment OTel attrs under X-Renate-Eval-Mode - (f701c6b) - Huy Le Duc

- - -

## backend-3.38.0 - 2026-10-21
#### Features
- (**chat**) expose all_sources and section/domain fields under X-Renate-Eval-Mode - (ceb24e7) - Huy Le Duc

- - -

## backend-3.37.1 - 2026-10-20
#### Bug Fixes
- (**migration**) quote reserved keywords in feedback DE->EN UpdateItem - (610badf) - Huy Le Duc

- - -

## backend-3.37.0 - 2026-10-19
#### Features
- (**backend**) sync Langfuse Score Configs from FEEDBACK_SCORE_SCHEMA (#941) - (8055d90) - Huy Le Duc

- - -

## backend-3.36.3 - 2026-10-19
#### Bug Fixes
- (**frontend**) regenerate api.generated.ts for English feedback literals - (05c16bb) - Huy Le Duc

- - -

## backend-3.36.2 - 2026-10-19
#### Bug Fixes
- (**backend**) handling_corrections → langfuse score, enforce rating literals (#909) - (41e80a9) - Huy Le Duc

- - -

## backend-3.36.1 - 2026-10-19
#### Bug Fixes
- (**backend**) emit real HTTP status on chat/feedback errors (#882) - (8d5d7bb) - Huy Le Duc

- - -

## backend-3.36.0 - 2026-10-16
#### Features
- (**backend**) read X-Langfuse-Trace-Tags on /api/chat - (a7137b4) - Huy Le Duc
#### Documentation
- (**analytics-reporting**) add runbook and mark manual report as override (TKT-AR-08) - (ce7a5c4) - Pfeiffer

- - -

## backend-3.35.4 - 2026-10-12
#### Bug Fixes
- (**Ticket-874**) adjusted internal feedback and openApi - (5d3122e) - lucy.stepanenko.extern

- - -

## backend-3.35.3 - 2026-10-12
#### Bug Fixes
- (**migration**) strip orphan feedback.thumbsUp=NULL rows (#905) - (901202c) - Huy Le Duc
#### Miscellaneous Chores
- (**ci**) manual migration jobs for feedback.thumbsUp → helpfulness (#905) - (c3804af) - Huy Le Duc

- - -

## backend-3.35.2 - 2026-10-12
#### Bug Fixes
- (**feedback**) emit user.helpfulness CATEGORICAL score for external 3-button rating (#905) - (c4139be) - Huy Le Duc

- - -

## backend-3.35.1 - 2026-10-09
#### Bug Fixes
- (**observability**) write langfuse.observation.input/output on root span - (0b5d3ab) - Huy Le Duc

- - -

## backend-3.35.0 - 2026-10-09
#### Features
- (**backend**) propagate langfuse session/user id to every span - (4d4fd6b) - Huy Le Duc

- - -

## backend-3.34.3 - 2026-10-09
#### Bug Fixes
- (**observability**) migrate score writes to /api/public/ingestion - (33d8097) - Huy Le Duc

- - -

## backend-3.34.2 - 2026-10-08
#### Bug Fixes
- (**observability**) send environment on langfuse v4 scores - (1303fd0) - Huy Le Duc

- - -

## backend-3.34.1 - 2026-10-08
#### Bug Fixes
- (**observability**) emit langfuse trace_id as undashed hex - (dcd1d7a) - Huy Le Duc

- - -

## backend-3.34.0 - 2026-10-08
#### Features
- (**feedback**) loop every feedback field to Langfuse scores (user.* schema) - (5ee5c1a) - Huy Le Duc

- - -

## backend-3.33.0 - 2026-10-07
#### Features
- (**feedback**) expand post_langfuse_score to all score types + FEEDBACK_SCORE_SCHEMA - (00e9d73) - Huy Le Duc

- - -

## backend-3.32.0 - 2026-10-07
#### Features
- (**chat**) expose trace_id in /api/chat response - (e3ad25b) - Huy Le Duc
#### Miscellaneous Chores
- (**faq-artifacts**) decommission shell publish path (monorepo #820) - (2620f8f) - Huy Le Duc

- - -

## backend-3.31.16 - 2026-09-28
#### Bug Fixes
- (**#871**) strip S3 URI from chunk storage, restore stable document grouping - (636459e) - Tobi Pfeiffer

- - -

## backend-3.31.15 - 2026-09-21
#### Bug Fixes
- (**Ticket-839**) adjusted model - (b0a06f4) - Lucy
#### Miscellaneous Chores
- (**ci**) retire monorepo retrieval-health-check shell path (#819 D) - (2383a45) - Huy Le Duc
- (**retention**) decommission scheduled retrieval-retention (narrow scope) - (524bb7a) - Huy Le Duc

- - -

## backend-3.31.14 - 2026-09-11
#### Bug Fixes
- (**ci**) finalize main rename — drop residual master refs - (a710430) - Huy Le Duc

- - -

## backend-3.31.13 - 2026-08-19
#### Bug Fixes
- (**langfuse**) protect content in telemetry (#750) - (21086b7) - Klaus Müller

- - -

## backend-3.31.12 - 2026-08-17
#### Bug Fixes
- (**analytics**) reconcile topic taxonomy with live domain classification - (9025810) - Aphrodite Arwanitidou

- - -

## backend-3.31.11 - 2026-08-14
#### Bug Fixes
- force full-retrieval to build the prod green slot (#671) - (2531cc7) - Felix

- - -

## backend-3.31.10 - 2026-08-14
#### Bug Fixes
- force full-retrieval path on the next retrieval promotion - (4f4bb47) - Felix

- - -

## backend-3.31.9 - 2026-08-12
#### Bug Fixes
- (**retrieval**) search with the user's own question, not only the rephrase - (75a226c) - Felix

- - -

## backend-3.31.8 - 2026-08-12
#### Bug Fixes
- (**retrieval**) break keyword-routing ties by retrieval rank - (3f4f53d) - Felix

- - -

## backend-3.31.7 - 2026-08-12
#### Bug Fixes
- (**retrieval**) score anchor selection on rank fusion, not raw scores - (3a70b82) - Felix

- - -

## backend-3.31.6 - 2026-08-12
#### Bug Fixes
- improve dashboard labels and topic classification - (c33766f) - Aphrodite Arwanitidou

- - -

## backend-3.31.5 - 2026-08-11
#### Bug Fixes
- recover canceled dev and ETL release - (b7d1907) - felixgeyer

- - -

## backend-3.31.4 - 2026-08-11
#### Bug Fixes
- (**retrieval**) recover prod diagnostics and activation rollback (#671) - (53f747c) - Felix

- - -

## backend-3.31.3 - 2026-08-11
#### Bug Fixes
- (**etl**) preserve Merkblatt PDF content during extraction - (29f13d3) - Felix
#### Miscellaneous Chores
- (**version**) 3.32.0 [skip ci] - (4f4d65d) - GitLab CI
- (**version**) 3.31.3 [skip ci] - (bad81a4) - GitLab CI

- - -

Changelog generated by [cocogitto](https://github.com/cocogitto/cocogitto).