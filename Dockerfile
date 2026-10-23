FROM node:22.14-alpine AS frontend

WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app
COPY pyproject.toml uv.lock README.md /app/
RUN python -m pip install uv==0.12.3 && uv sync --frozen --no-dev --no-install-project
COPY src /app/src
COPY configs /app/configs
COPY --from=frontend /web/dist /app/frontend/dist
RUN uv sync --frozen --no-dev --no-editable && rm -rf /tmp/uv-cache
RUN mkdir -p /var/lib/transit-delay && chown -R app:app /var/lib/transit-delay /app
USER app
EXPOSE 8000
CMD ["transit-delay", "serve", "--config", "configs/vps.yaml"]
