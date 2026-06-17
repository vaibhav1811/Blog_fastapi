# BUILD STAGE
FROM python:3.14.4-slim-bookworm AS builder

# Copy UV binary from official image
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/  


WORKDIR /app

# UV Docker optimizations
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=0

# Install dependencies first (cached if unchanged)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Copy app code and install project
#this comes after installing dependencies to leverage Docker caching. If the app code changes but dependencies don't, Docker will reuse the cached layer for dependencies and only re-run the layer that copies the app code and installs the project. This speeds up builds when making changes to the app code without modifying dependencies.
COPY . ./
RUN uv sync --locked --no-dev

# PRODUCTION STAGE
FROM python:3.14.4-slim-bookworm

WORKDIR /app

# Run as non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Copy app and dependencies from builder stage
COPY --from=builder --chown=appuser:appuser /app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Run migrations then start the server.
# `alembic upgrade head` is idempotent — it only applies pending migrations
# and is safe to run on every deploy. Using `&&` ensures the server only
# starts if migrations succeed, preventing a broken app from coming online.
CMD ["/bin/sh", "-c", "alembic upgrade head && exec fastapi run --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*'"]