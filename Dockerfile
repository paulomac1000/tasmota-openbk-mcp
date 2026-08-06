FROM python:3.13.5-slim@sha256:8df0e8c47e9fdfc3abf4f098453051f8f4c2202be8c0d2d3850058adf3a58517

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system mcp && useradd --system --gid mcp --home /app mcp
WORKDIR /app
COPY dist/*.whl /tmp/package.whl
COPY requirements.lock /tmp/requirements.lock
COPY wheelhouse/ /tmp/wheelhouse/
RUN python -m pip install --no-cache-dir \
      --no-index --find-links=/tmp/wheelhouse --require-hashes \
      -r /tmp/requirements.lock \
    && python -m pip install --no-cache-dir --no-index --no-deps /tmp/package.whl \
    && rm -rf /tmp/package.whl /tmp/requirements.lock /tmp/wheelhouse
RUN mkdir -p /app/data/artifacts && chown -R mcp:mcp /app
USER mcp

ENV MCP_TRANSPORT=http \
    BIND_HOST=127.0.0.1 \
    MCP_PORT=9102 \
    MCP_PATH=/mcp \
    MCP_ARTIFACT_ROOT=/app/data/artifacts

EXPOSE 9102
ENTRYPOINT ["local-home-devices-mcp"]
