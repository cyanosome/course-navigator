FROM ghcr.io/astral-sh/uv:python3.14-alpine

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/backend_app/.venv-api
ENV PATH="/backend_app/.venv-api/bin:$PATH"

WORKDIR /backend_app

# Install build dependencies for compiling asyncpg from source (required for Python 3.14 on Alpine)
RUN apk add --no-cache gcc musl-dev python3-dev

# Copy workspace root files and package sources needed for API & Agent
COPY pyproject.toml uv.lock ./
COPY core ./core
COPY agent ./agent
COPY api ./api

# Sync dependencies for course-api (includes core, agent)
RUN uv sync --frozen --package course-api

CMD ["uv", "run", "--package", "course-api", "fastapi", "dev", "api/src/api/main.py", "--host", "0.0.0.0", "--port", "8000"]
