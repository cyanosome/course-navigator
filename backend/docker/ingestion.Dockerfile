FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/backend_app/.venv-ingestion
ENV PATH="/backend_app/.venv-ingestion/bin:$PATH"

WORKDIR /backend_app

# Install build dependencies and OS libraries for scraping / PDF parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace root files and package sources needed for Ingestion
COPY pyproject.toml uv.lock ./
COPY core ./core
COPY ingestion ./ingestion

# Sync dependencies for course-ingestion (includes core)
RUN uv sync --frozen --package course-ingestion

CMD ["uv", "run", "--package", "course-ingestion", "python", "-m", "ingestion.ingester"]
