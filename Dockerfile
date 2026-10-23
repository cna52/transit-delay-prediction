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
RUN uv sync --frozen --no-dev --no-editable && rm -rf /tmp/uv-cache
RUN mkdir -p /var/lib/transit-delay && chown -R app:app /var/lib/transit-delay /app
USER app
EXPOSE 8000
CMD ["transit-delay", "serve", "--config", "configs/vps.yaml"]
