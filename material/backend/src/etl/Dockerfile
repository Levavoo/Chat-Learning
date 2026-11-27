# Multi-stage build for AWS Lambda with uv
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

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
FROM public.ecr.aws/lambda/python:3.14

# Copy dependencies to the Lambda task root
COPY --from=builder /build/.venv/lib/python3.14/site-packages/ ${LAMBDA_TASK_ROOT}/

# Copy shared modules and etl source code
COPY backend/src/bm25_shared/ ${LAMBDA_TASK_ROOT}/bm25_shared/
COPY backend/src/etl/ ${LAMBDA_TASK_ROOT}/etl/
COPY backend/src/etl/config.yaml ${LAMBDA_TASK_ROOT}/config.yaml

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Lambda handler
CMD ["etl.lambda_function.lambda_handler"]
