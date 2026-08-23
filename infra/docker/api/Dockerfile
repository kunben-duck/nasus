FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Pin and prefetch the external graph provider at image build time. Runtime
# never downloads executables on first traffic and can run with egress denied.
ARG CODEBASE_MEMORY_MCP_VERSION=0.8.1
RUN pip install "codebase-memory-mcp==${CODEBASE_MEMORY_MCP_VERSION}" \
    && codebase-memory-mcp --version

COPY apps /app/apps

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "apps.api.app.main:app", "--app-dir", ".", "--host", "0.0.0.0", "--port", "8000"]
