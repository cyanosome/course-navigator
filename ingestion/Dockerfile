FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/ingestion_app/.venv

WORKDIR /ingestion_app

ENV PATH="/ingestion_app/.venv/bin:$PATH"

# Install build dependencies for compiling C-extensions (such as asyncpg on Python 3.14)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .

CMD ["tail", "-f", "/dev/null"]
