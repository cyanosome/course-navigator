FROM ghcr.io/astral-sh/uv:python3.14-alpine

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/ingestion_app/.venv
ENV PATH="/ingestion_app/.venv/bin:$PATH"

WORKDIR /ingestion_app

# Install build dependencies if needed
RUN apk add --no-cache gcc musl-dev python3-dev

# Ingestion pipeline entrypoint (placeholder)
CMD ["echo", "Ingestion container is ready."]
