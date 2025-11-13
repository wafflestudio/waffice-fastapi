# Multi-stage build for arm64 Linux
# Stage 1: Builder
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files first (for layer caching)
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
# Using --no-dev to exclude development dependencies in production
RUN uv sync --no-dev

# Stage 2: Runtime
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install uv in runtime (needed to run the app)
RUN pip install --no-cache-dir uv

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY app ./app

# Build argument for environment
ARG ENV=dev
ENV ENV=${ENV}

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose FastAPI port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/docs').getcode()" || exit 1

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
