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

# Render mounts Secret Files at /etc/secrets/<name> readable by group 1000
# (render.com/docs/docker-secrets), which the base image doesn't have. The runtime
# user joins that one group, so it can read a private bundle installed there
# (HEROOS_KNOWLEDGE_BUNDLE_PATH, HEROOS_EXECUTION_PROFILE_PATH); it stays non-root.
RUN groupadd --system --gid 1001 heroos \
    && groupadd --gid 1000 render-secrets \
    && useradd --system --uid 1001 --gid heroos --groups render-secrets heroos

COPY --from=builder /app/.venv /app/.venv

COPY --chown=heroos:heroos apps/api/app ./app

# Public Supabase Root 2021 CA for `sslmode=verify-full` on DATABASE_URL
# (docs/operations/demo-authentication-deployment.md §5). Root-owned and 0444:
# the runtime user can read it but not replace it, and no platform secret file
# is needed. --chmod also makes the mode independent of the build checkout's
# umask. The directory is created first: a directory COPY creates inherits
# --chmod, and 0444 would make it untraversable.
RUN install -d -m 0755 /app/certs
COPY --chmod=0444 apps/api/certs/supabase-root-2021-ca.crt /app/certs/supabase-root-2021-ca.crt

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
