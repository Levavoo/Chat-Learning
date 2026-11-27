# ETL Package

Document processing and knowledge base ingestion pipeline

## Overview

ETL package provides configurable, event-driven data processing pipelines for:

- **Ingesting** documents from `S3` or the local file-system
- **Transforming** documents (format conversion, metadata extraction, chunking)
- **Outputting** processed documents to `S3` or local storage

Supports multiple document formats: `DITA XML, HTML, PDF, Markdown`.

## Architecture

### Core Components

```text
┌─────────┐     ┌───────────┐     ┌────────┐
│ Ingest  │ --> │ Transform │ --> │ Output │
└─────────┘     └───────────┘     └────────┘
        Orchestrated by Pipeline
```

#### 1. **Ingest** (`etl/ingest/`)

Reads data from repositories:

- `S3Ingest`: Read from S3 buckets
- `LocalFileIngest`: Read from filesystem
- `HTMLIngest`: Fetch HTML from URLs

#### 2. **Transform** (`etl/transform/`)

Processes documents through transformation chain:

- `convert_to_md.py` (TEXT2MD): Convert various formats to clean Markdown. Emits
  no YAML frontmatter — custom metadata lives only in the `.metadata.json`
  sidecar, so the body Bedrock embeds and BM25 returns is identical to the stored
  `.md` (#696).
- `convert_to_html.py` (DITA2HTML): Convert DITA XML to HTML
- `extract_metadata.py` (META_FROM_DITA): Extract metadata from DITA
- `chunk_markdown.py` (CHUNK_MARKDOWN): Split Markdown into chunks
- `filter_html.py` (PrepareFAQHTML): Clean/filter HTML
- `filter_md.py`: Filter Markdown content

**Chunking Strategies** (`etl/util/chunking/`):

- `FlatSectionStrategy`: Simple section-based chunking
- `HierarchicalStrategy`: Nested section chunking with parent context
- `SemanticStrategy`: Semantic similarity-based chunking
- `GlossaryStrategy`: Specialized glossary term chunking

#### 3. **Output** (`etl/output/`)

Writes processed data:

- `S3Output`: Write to S3 buckets
- `LocalFileOutput`: Write to filesystem

#### 4. **Pipeline** (`etl/pipeline/`)

Orchestrates ETL flow:

- Runs ingests asynchronously
- Executes transform chain with validation
- Exports to all configured outputs
- Validates transform type compatibility

#### 5. **Router** (`etl/pipeline/router.py`)

Central configuration manager:

- Matches events to routes using pattern matching
- Manages repositories, pipelines, routes
- Supports regex patterns for flexible matching
- Singleton pattern for global access

### Data Models (`etl/models.py`)

- **`DataType`**: Enum of supported formats (TEXT, JSON, XML, MARKDOWN, PDF, HTML)
- **`DataObject`**: Raw data with metadata
- **`SourceObject`**: Source metadata
- **`PipelineItem`**: Container for data flowing through pipeline
- **`OutputData`**: Metadata about exported data

## Configuration

Central config: `etl/config.yaml`

### Structure

```yaml
repositories:
  REPO_NAME:
    type: 'S3' # or "LocalFilesystem"
    bucket_name: '${ETL_INGEST_BUCKET}' # Env var expansion

routes:
  ROUTE_NAME:
    match:
      source: 'aws:s3'
      repositories: ['INGEST_BUCKET']
      prefix: ['IN/'] # Match prefix pattern
      postfix: ['.xml'] # Match file extension
    pipeline: 'PIPELINE_NAME' # Or {name: "NAME", config: {...}}
    destinations:
      OUTPUT_NAME:
        repository: OUTPUT_BUCKET
        path: 'docs'

pipelines:
  PIPELINE_NAME:
    transforms:
      - META_FROM_DITA
      - DITA2HTML
      - TEXT2MD
      - CHUNK_MARKDOWN
```

### Pattern Matching

Router supports flexible matching:

- **Exact match**: `postfix: ".xml"`
- **List match**: `prefix: ["IN/", "DOCS/"]` (OR logic)
- **Regex**: Any pattern with metacharacters
- **Multiple criteria**: All must match (AND logic)

## Usage

### AWS Lambda Deployment

Triggered by S3 events or SQS messages:

```python
# lambda_function.py entry point
def lambda_handler(event, context):
    # Auto-routes S3 ObjectCreated events to configured pipelines
    # Processes: parse event → match route → run pipeline
```

**Supported event sources:**

- `aws:s3`: Direct S3 notifications
- `aws:sqs`: SQS-wrapped S3 events

### Local Execution

```bash
# Run manual routes
python -m etl.main

# Or with environment
uv run python -m etl.main
```

Manual routes defined with `source: "manual"` in config.

### Programmatic Usage

```python
from etl.pipeline.router import initialize_router
from etl.pipeline.base import Pipeline
from etl.util.repository.base import Repository

# Initialize router from config
router = initialize_router()

# Create repositories
repos = {
    name: Repository.create(config.type, **config.to_kwargs())
    for name, config in router.list_repositories().items()
}

# Build and run pipeline
match = router.match_route(
    source="aws:s3",
    bucket_name="my-bucket",
    object_key="docs/example.xml"
)

if match:
    config = router.build_pipeline_config(
        match, ["example.xml"], "REPO_NAME"
    )
    pipeline = Pipeline.create(config, repos)
    await pipeline.run()
```

## Adding Components

### New Transform

```python
# etl/transform/my_transform.py
from etl.models import DataType, PipelineItem
from etl.transform.base import Transform

class MyTransform(Transform):
    transform_type = "MY_TRANSFORM"  # Used in config
    supported_input_types = [DataType.MARKDOWN]
    output_type = DataType.MARKDOWN

    def apply(self, item: PipelineItem) -> list[PipelineItem]:
        # Process item.data_object.data
        # Return list of transformed items
        return [item]
```

Register in config:

```yaml
pipelines:
  MY_PIPELINE:
    transforms:
      - MY_TRANSFORM
```

### New Repository Type

```python
# etl/util/repository/my_repo.py
from etl.util.repository.base import Repository

class MyRepository(Repository):
    repository_type = "MyRepo"

    async def read(self, path: str) -> bytes:
        # Implement read logic
        pass

    async def write(self, path: str, data: bytes) -> str:
        # Implement write logic
        return "output_id"
```

### New Chunking Strategy

```python
# etl/util/chunking/my_strategy.py
from etl.util.chunking.base import ChunkingStrategy

class MyStrategy(ChunkingStrategy):
    strategy_type = "my_strategy"

    def chunk(self, content: str, metadata: dict) -> list[dict]:
        # Return list of {text, metadata} dicts
        return [{"text": content, "metadata": metadata}]
```

## Directory Structure

```text
etl/
├── config/              # Settings and AWS config
├── config.yaml          # Main pipeline configuration
├── executor/            # Execution environments (local, etc.)
├── ingest/              # Data source adapters
├── output/              # Data destination adapters
├── pipeline/            # Pipeline orchestration and routing
├── transform/           # Document transformation modules
├── util/
│   ├── aws/            # AWS utilities (Lambda handlers)
│   ├── chunking/       # Chunking strategies
│   ├── parsing/        # Document parsers (DITA, etc.)
│   ├── repository/     # Repository implementations
│   └── logging_setup/  # Logging configuration
├── lambda_function.py   # AWS Lambda entry point
├── main.py             # Local CLI entry point
└── models.py           # Shared data models
```

## Key Features

- **Event-driven**: Auto-processes S3 uploads via Lambda
- **Configurable**: YAML-based pipeline definitions
- **Extensible**: Plugin architecture for transforms/repositories
- **Type-safe**: Validates transform chain compatibility
- **Async**: Parallel processing of multiple documents
- **Pattern matching**: Flexible routing with regex support
- **Multiple formats**: DITA, HTML, PDF, Markdown
- **Smart chunking**: Multiple strategies for optimal retrieval

## Environment Variables

```bash
ETL_INGEST_BUCKET=my-ingest-bucket
ETL_OUTPUT_BUCKET=my-output-bucket
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

## Testing

```bash
# Run ETL tests
make backend-test

# Or directly
cd backend
uv run pytest tests/etl/
```

## Generated-artifact quality gate (#694)

Structural quality is validated at three layers:

```text
source_quality (#680, DITA XML)  ->  extraction fix (#501, PDF)  ->  markdown_quality (#694, generated .md)
```

`markdown_quality.py` is a pure scanner (stdlib + `re` only, no `boto3`, no
pipeline import) that flags structural defects in the generated Markdown chunks —
`md.control-character`, `md.duplicate-leading-separator`, `md.orphan-bullet`,
`md.empty-printed-page-reference`, `md.non-utf8`, `md.empty-document` (hard) plus
`md.embedded-pdf-page-counter` and `md.split-boundary-start` (warning; an
_unreviewed_ warning still fails the gate). It reuses `source_quality`'s report +
acknowledgement engine and vocabulary (`decision` in
`{source_fix_requested, accepted}`), and additionally accepts a document-folder
`source` (e.g. `docs/G0103/`) so a baseline entry survives chunk-index churn.

`markdown_quality_gate.py` reproduces the corpus offline: it runs the _real_
transform chain (incl. `CHUNK_MARKDOWN`) over `cdk/seed-data/source` into a temp
dir via local repositories, then scans it. Run it with `make kb-markdown-quality`;
the CI job `kb-markdown-quality` runs it before `build-data-artifacts` publishes
(a failed gate blocks publication via `needs`).

**Determinism invariant:** generation forces `CONTEXTUAL_GROUNDING_ENABLED` and
`ENRICHMENT_ENABLED` off. Contextual grounding is the only step that mutates chunk
_content_ and every configured env sets it `false`; enrichment is metadata-only.
So the generated `.md` bytes are deterministic and byte-identical to the deployed
runtime `.md` content, and generation needs no Bedrock/S3. **If any env ever sets
`contextualGrounding.enabled: true`, the runtime `.md` gains a non-deterministic
prefix and this gate's parity must be revisited.**

The current residue (owned by #501/#680) is baselined in
`cdk/seed-data/markdown-quality-acknowledgements.json` as `source_fix_requested`
entries; the gate surfaces an entry as stale once its document regenerates clean,
driving baseline removal. Regenerate the baseline with
`make kb-markdown-quality-baseline` (review the diff before committing).

## Deployment Impact of Changes Here

Editing anything in this package is not a code-only change — it decides how the
next retrieval promotion runs.

`.gitlab/ci/scripts/build/etl-changed.sh` content-hashes `backend/src/etl/`,
`backend/src/bm25_shared/`, `pyproject.toml`, `uv.lock` and
`backend/pyproject.toml`. Any change to those flips `ETL_IMAGE_CHANGED`, which
rebuilds the ETL image and re-tags it with the new release version. A new
`etl_version` changes the retrieval artifact ID, and that is what
`retrieval-orchestration.mjs decide-path` compares — so the next QA and preprod
promotions take the **`full-retrieval`** path rather than **`chatbot-only`**.

### Recovering a canceled ETL release

A master pipeline can be canceled after Cocogitto has consumed the release
commits or published an image pointer, but before the ETL and application are
deployed. A later pipeline then reports `BUMPED=false` and correctly skips the
release jobs; manually changing an environment pin would bypass the deployment
and smoke-test gates.

Recover by merging a small, reviewable MR with an unscoped conventional `fix:`
title so Cocogitto creates the next patch release. If the ETL also needs a fresh
coordinate, the MR must include a genuine change to one of the inputs listed
above. This runbook clarification is inside `backend/src/etl/`, so it is itself
an ETL image fingerprint input: the recovery release will build and publish
`v<NEW_TAG>` and will exercise the `full-retrieval` promotion path. The data
artifact remains independently content-gated and is reused unless the source
corpus changes.

After the master pipeline succeeds, verify `deploy-etl:dev`, `cdk-deploy:dev`,
`smoke-eval:dev`, and `open-qa-mr` before merging the generated QA promotion MR.

The two paths cost very different amounts:

| path             | what runs                                                                            | measured                   |
| ---------------- | ------------------------------------------------------------------------------------ | -------------------------- |
| `chatbot-only`   | redeploy the chat Lambda, rewrite the manifests. No corpus work, no slot change.     | ~130 s (preprod job 18274) |
| `full-retrieval` | build the whole corpus into the **inactive** blue/green slot, then flip the selector | ~17.5 min (qa job 17765)   |

`full-retrieval` breaks down roughly as:

| phase                                                  | elapsed |
| ------------------------------------------------------ | ------- |
| verify both image digests are recoverable from ECR     | 97 s    |
| deploy the exact ETL image to the inactive slot        | 128 s   |
| process the pinned raw corpus into the inactive prefix | 304 s   |
| wait for the Bedrock knowledge-base ingestion job      | 225 s   |
| freeze and verify the candidate corpus                 | 65 s    |
| build and validate the immutable BM25 index            | ~205 s  |

Three of those phases process the entire corpus, so they scale with corpus size
rather than with the size of your change — a one-line edit here costs the same
as a rewrite.

This is also the only way the inactive blue/green slot is exercised. A run of
`chatbot-only` promotions leaves one slot untouched indefinitely.

### Observed in production (#671, 2026-08-14)

Prod reached exactly the state the paragraph above warns about. Successive
`chatbot-only` promotions left **both** selectors pointing at the blue knowledge
base (`P3OEBMERZQ`); the green slot (`4RKYJFKOL0`) had never been built. The two
releases differed only in `release_id`, `version` and `chatbot_image_digest`,
with identical `retrieval_artifact_id`, `processed_prefix`, `bm25_key`,
`etl_version` and `etl_image_digest`.

That has two consequences beyond the untouched slot:

- `deploy-prod-retrieval-monitoring.sh` fails closed with `previous manifest
does not select the inactive green slot`. It derives _both_ slots' ETL image
  digests from the two live selectors, so it cannot resolve a green digest while
  both selectors sit in blue. #671's alarm-action activation stays blocked until
  a genuine pair exists.
- A rollback drill across such a pair proves nothing. Both selectors resolve the
  same corpus and BM25 index, so the swap changes only the chatbot image and
  cannot demonstrate the #493 retrieval RTO.

Recovery requires one `full-retrieval` promotion, which builds the corpus into
the inactive slot and flips the selector. Since every file under
`backend/src/etl/` is an IMAGE-set fingerprint input — `etl-changed.sh` walks the
directory with `find -type f` and hashes contents, with no extension filter —
editing this file is the documented way to force that path on the next release.
Note that only `feat:`/`fix:` titles bump a release, and `etl-changed:dev` exits
early unless `BUMPED=true`, so a `docs:`-titled change would leave the promotion
path on `chatbot-only`.

#### Promotion-role permission the enumeration needs

Resolving the outgoing chatbot digest enumerates every image-backed Lambda in the
chatbot stack. That enumeration must use the paginated
`cloudformation:ListStackResources`: `DescribeStackResources` caps at 100
resources with no continuation token, and `renate-chatbot-prod` has 142, so the
truncated window hid `renate-chat-prod` and `renate-health-prod` and left the
digest check silently verifying only the analytics Lambda. The
`ki-lab-digibro-<env>-retrieval-promotion` roles were granted only the capped
call, so the corrected implementation failed closed with `could not list Lambda
functions for stack renate-chatbot-qa` until `ListStackResources` was added to
their `InspectPromotionStacks` statement (`renate/bootstrap!54`). A promotion that
aborts here has not mutated anything: the call happens during read-only selector
and slot resolution, before the first live write.

## Related Documentation

- DITA Parsing: `etl/util/parsing/dita.py`
- Chunking: `docs/analysis/chunking-analysis.md`
- Lambda Handlers: `etl/util/aws/lmbda/handler.py`
