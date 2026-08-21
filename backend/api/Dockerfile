FROM ghcr.io/astral-sh/uv:python3.14-alpine

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/backend_app/.venv

WORKDIR /backend_app

ENV PATH="/backend_app/.venv/bin:$PATH"

# Install build dependencies for compiling asyncpg from source (required for Python 3.14 on Alpine)
RUN apk add --no-cache gcc musl-dev python3-dev

# Copy workspace root files and package sources
COPY pyproject.toml uv.lock ./
COPY core ./core
COPY api ./api
COPY ingestion ./ingestion
COPY agent ./agent

RUN uv sync --frozen --package course-api

CMD ["tail", "-f", "/dev/null"]
