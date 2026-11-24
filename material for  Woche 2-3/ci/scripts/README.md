# CI scripts

Shell and Node scripts invoked from `.gitlab/ci/**/*.yml` jobs. Layout mirrors
GitLab pipeline stages so a job that fails in stage `deploy` maps to `deploy/`
without further hunting.

## Layout

| Dir         | Contents                                                            |
| ----------- | ------------------------------------------------------------------- |
| `validate/` | MR gates — pin format, promotion source, tooling assertions         |
| `build/`    | Artifact publishing — data, FAQ, ETL image metadata                 |
| `deploy/`   | Environment/stack deploys, activation, chatbot/retrieval candidates |
| `verify/`   | Post-deploy readiness checks, smoke evals, health checks            |
| `release/`  | Deployment page rendering, tag pushing, MR opening, notifications   |
| `teardown/` | Review environment cleanup, retention reconciliation                |
| `ops/`      | Manually-triggered maintenance switches, rollbacks                  |
| `util/`     | Cross-cutting primitives called by scripts in multiple stage dirs   |
| `lib/`      | Bash libraries — sourced, never executed standalone                 |
| `lib/node/` | Node modules — imported, never executed except via a stage-dir call |
| `tests/`    | Bats + `node --test` suites, one subdir per source dir              |

## Rules for adding a script

1. **New script for a pipeline job?** Put it in the stage dir that matches the
   job's `stage:` in yaml. A job in `stage: deploy` calls scripts in `deploy/`.
2. **Called from two or more stage dirs?** It's a primitive — move it to
   `util/` (e.g. `bm25-rebuild.sh` runs from both `build/` and `deploy/`).
3. **Never executed standalone, only sourced/imported?** Put it in `lib/` (bash)
   or `lib/node/` (Node). If it has a shebang and gets executed, it's not lib.
4. **Add a mirroring test file** under `tests/<same-subdir>/`, then extend the
   matching `test:ci-scripts:<subdir>` job in `.gitlab/ci/validate/deploy.yml`
   with the new path under `changes:` if it isn't already covered by a glob.

## Key flows

Entry points, in the order the pipeline runs them.

| Flow                         | Trigger                                                                   | Entry scripts                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| dev deploy                   | push to `master`                                                          | `deploy/deploy-dev.sh` → `verify/smoke-eval-dev.sh` → `release/render-deployment-page.sh` + `release/open-qa-mr.sh`                       |
| ETL deploy (dev)             | ETL/CDK change on `master`                                                | `build/etl-changed.sh` → `build/publish-image-metadata.sh` → `deploy/deploy-and-verify-etl-dev.sh` → `util/bm25-rebuild.sh` (conditional) |
| data-artifact publish        | knowledge-base content change                                             | `build/compose-data-artifact.sh` → `build/upload-data-artifacts.sh`                                                                       |
| FAQ artifact publish         | scheduled (Lambda in `renate/scheduled-jobs`) + manual                    | `renate/scheduled-jobs/jobs/faq-artifact-refresh` (Lambda, `cron(0 9 ? * TUE *)` Europe/Berlin, origin #591)                              |
| qa promotion                 | dev deploy success                                                        | `release/open-qa-mr.sh` (MR) → merge → `deploy/deploy-env.sh qa` → `deploy/deploy-qa-retrieval-*.sh` → `deploy/activate-qa-retrieval.sh`  |
| preprod promotion            | qa deploy success                                                         | `validate/check-promotion-source.sh preprod` → `deploy/preflight-preprod-retrieval-foundation.sh` → `deploy/deploy-env.sh preprod`        |
| preprod blue baseline (#642) | preprod pin bumped                                                        | `validate/validate-preprod-blue-baseline.sh` → `deploy/activate-preprod-blue-baseline.sh`                                                 |
| retrieval health / rollback  | scheduled (Lambda in `renate/scheduled-jobs`) + manual                    | `renate/scheduled-jobs/jobs/retrieval-health-check` (Lambda, `rate(15 minutes)`) → `ops/rollback-qa-retrieval.sh` (manual)                 |
| maintenance switch           | `deployments/<env>/maintenance.yaml` change or manual `MAINTENANCE_STATE` | `ops/maintenance-switch.sh <env>`                                                                                                         |
| review env teardown          | MR closed or scheduled sweep                                              | `teardown/review-cleanup.sh` (+ `teardown/review-check-cleanup.sh`)                                                                       |
| qa retention reconcile       | scheduled                                                                 | `teardown/reconcile-qa-retrieval-retention.sh`                                                                                            |

## Recovering a canceled release pipeline

A release pipeline can be canceled by a newer push after Cocogitto has created
the version tag and the build jobs have published new image pointers, but before
`cdk-deploy:dev` and `open-qa-mr` finish. A later pipeline does not recover that
release automatically: Cocogitto has already consumed its conventional commits,
so the later pipeline exports `BUMPED=false` and the deployment and promotion
jobs intentionally no-op.

Do not promote the orphaned version directly. The SSM image pointer may already
contain the new tag while the live Lambda still resolves to the previous image.
Recover through the normal versioned pipeline instead:

1. Confirm that no dev deployment or QA promotion is still running, and compare
   the live dev Lambda image with `/dev/renate/image-tag`.
2. Merge a small, reviewable recovery MR with an unscoped conventional `fix:`
   title. The MR must contain a real operational documentation or pipeline fix;
   do not create an empty release commit.
3. Let Cocogitto create the next patch version. This release contains all
   commits from the canceled releases and runs the current deployment logic.
4. Wait for `cdk-deploy:dev`, `smoke-eval:dev`, and `open-qa-mr` to succeed,
   then review and merge the generated QA promotion MR.

ETL and data coordinates remain content-gated. For an application-only
recovery, they are reused when their fingerprints are unchanged. If the ETL
release must also receive a fresh coordinate, include a genuine change to an
ETL-owned fingerprint input, such as its operational documentation; see
`backend/src/etl/README.md`. Never edit an environment version pin merely to
force a promotion.

## Growth guide

The verb-per-stage split scales linearly with pipeline complexity. Reach for a
larger restructure only when one of these actually happens:

- A stage dir accumulates a second **independent domain** (e.g. document
  ingestion pipeline that shares nothing with retrieval). Split by domain
  first — `deploy/retrieval/` and `deploy/ingestion/` — before splitting the
  repo.
- Primitives outgrow `util/` (>10 files with distinct lifecycles). Consider a
  `bin/`/`libexec/` split at that point, not before.
- A stage dir passes ~25 scripts. Group by feature area with a nested subdir;
  keep the flat layout for smaller counts.

Until then, the shape above is intentionally simple.
