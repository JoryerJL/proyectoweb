# syntax=docker/dockerfile:1

# ---- Builder: resolve and install locked dependencies with uv ----------------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock ./
# The project itself is not a package we need installed; only its dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- Runtime ------------------------------------------------------------------
FROM python:3.14-slim AS runtime

# Links the GHCR package to the repository (visibility, permissions, README).
LABEL org.opencontainers.image.source="https://github.com/JoryerJL/proyectoweb"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_STATIC_ROOT=/var/www/static \
    DJANGO_MEDIA_ROOT=/var/www/media

# libpq5: required by psycopg (pure-Python build); curl: container healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /var/www/static /var/www/media \
    && chown -R app:app /var/www

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .
RUN chmod +x /app/deploy/entrypoint.sh

USER app
EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "canaco.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
