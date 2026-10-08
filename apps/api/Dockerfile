FROM python:3.12.13-slim AS builder

ENV UV_VERSION=0.12.2
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY apps/api/pyproject.toml apps/api/uv.lock ./

RUN uv sync \
    --frozen \
    --no-dev \
    --no-install-project


FROM python:3.12.13-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN groupadd --system --gid 1001 heroos \
    && useradd --system --uid 1001 --gid heroos heroos

COPY --from=builder /app/.venv /app/.venv

COPY --chown=heroos:heroos apps/api/app ./app

USER heroos

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=3s \
    --start-period=5s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

# --no-access-log: Uvicorn's access log records the raw request target, including
# query strings. The application's structured request_completed event (route
# template, status, duration, request ID) is the authoritative request log.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
