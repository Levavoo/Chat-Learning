# Multi-stage build for AWS Lambda with uv
# Pin to linux/amd64: Lambda runs x86_64, and building on ARM (e.g. Apple Silicon)
# would otherwise produce ARM-native wheels / image that crash at runtime.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

WORKDIR /build

# Environment variables for uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1

# Copy workspace root and backend dependency files
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md ./backend/

# Install dependencies only (no project code)
RUN cd backend && uv sync --frozen --no-install-project --no-dev

# Runtime stage - AWS Lambda Python base image
FROM --platform=linux/amd64 public.ecr.aws/lambda/python:3.14

# Copy installed dependencies with proper ownership
COPY --from=builder --chown=1000:1000 /build/.venv/lib/python3.14/site-packages/ ${LAMBDA_TASK_ROOT}/

# Copy shared modules and backend_orchestrator source code with proper ownership
COPY --chown=1000:1000 backend/src/bm25_shared/ ${LAMBDA_TASK_ROOT}/bm25_shared/
COPY --chown=1000:1000 backend/src/backend_orchestrator/ ${LAMBDA_TASK_ROOT}/backend_orchestrator/

# Brochure priority map — read at runtime by kb_retrieval._load_priority_map.
# Config default BROCHURE_PRIORITY_FILE="data/brochure_priorities.json" (relative to Lambda cwd = /var/task).
COPY --chown=1000:1000 backend/data/ ${LAMBDA_TASK_ROOT}/data/

# Fix file permissions for Lambda runtime
RUN chmod -R 755 ${LAMBDA_TASK_ROOT}

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    AWS_REGION=eu-central-1 \
    AWS_DEFAULT_REGION=eu-central-1

# Lambda handler - package is installed in site-packages
CMD ["backend_orchestrator.orchestrator.lambda_handler"]
