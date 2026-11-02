# One image for both Cloud Run services (Step 30.1):
#   API:    HSOS_ASGI_APP=app.main:app          (default)
#   Worker: HSOS_ASGI_APP=app.workers.main:app
# Synthetic fixtures and tests are not shipped; content/ (reviewed packs) is.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /srv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim
WORKDIR /srv
COPY --from=build /srv/.venv /srv/.venv
COPY app ./app
COPY content ./content
ENV PATH=/srv/.venv/bin:$PATH PYTHONUNBUFFERED=1 PORT=8080 \
    HSOS_ASGI_APP=app.main:app HSOS_LOG_FORMAT=json
USER 10001
CMD ["sh", "-c", "exec uvicorn \"$HSOS_ASGI_APP\" --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10"]
