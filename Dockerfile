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

# App writes poker.db next to main.py
RUN chown -R app:app /app

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
