FROM ghcr.io/astral-sh/uv:python3.14-alpine

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/backend_app/.venv
ENV PATH="/backend_app/.venv/bin:$PATH"

WORKDIR /backend_app

# Install build dependencies for compiling asyncpg from source (required for Python 3.14 on Alpine)
RUN apk add --no-cache gcc musl-dev python3-dev

# Copy project definition, lock file, and README
COPY pyproject.toml uv.lock README.md ./

# Copy source code and seed data
COPY src ./src
COPY seed ./seed

# Sync dependencies
RUN uv sync --frozen

CMD ["uv", "run", "fastapi", "dev", "src/api/main.py", "--host", "0.0.0.0", "--port", "8000"]
