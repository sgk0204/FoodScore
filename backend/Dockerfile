# syntax=docker/dockerfile:1.7
# One image, two processes: the API (default CMD) and the ARQ worker (override CMD).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py \
    && pip install --prefix=/install .

FROM base AS runtime
RUN groupadd --system app && useradd --system --gid app --home /app app
COPY --from=deps /install /usr/local
COPY --chown=app:app . .
RUN pip install --no-deps -e . && mkdir -p /app/.data && chown app:app /app/.data
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/health' % __import__('os').environ.get('PORT','8000')).status==200 else 1)"
# PORT is set by hosts like Render. --proxy-headers so client IPs (rate limits, guest quotas) come from X-Forwarded-For.
CMD ["sh", "-c", "alembic upgrade head && uvicorn --factory app.main:app_factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
