# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.12.3 AS uv

FROM docker.io/library/python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    CONTROLPLANE_DB_PATH=/app/var/controlplane.db

WORKDIR /app

COPY --from=uv /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY config ./config
COPY data ./data

RUN uv sync --frozen --no-dev --no-editable \
    && groupadd --system --gid 10001 controlplane \
    && useradd --system --uid 10001 --gid controlplane --home-dir /app --shell /usr/sbin/nologin controlplane \
    && mkdir -p /app/var \
    && chown -R controlplane:controlplane /app/var

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
