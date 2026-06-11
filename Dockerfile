# Build stage: install locked dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Runtime stage
FROM python:3.14-slim-bookworm

RUN groupadd --system app && useradd --system --gid app app

WORKDIR /app/backend

COPY --from=builder /app/backend/.venv .venv
COPY backend/ ./
COPY frontend/ ../frontend/

# DB lives in /app/data — mount a volume there to persist it (host dir must be
# writable by the app user, uid 999)
RUN mkdir -p /app/data && chown -R app:app /app

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    POKER_DB_PATH=/app/data/poker.db

USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
