# syntax=docker/dockerfile:1.7
FROM python:3.14-slim@sha256:44dd04494ee8f3b538294360e7c4b3acb87c8268e4d0a4828a6500b1eff50061

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    BIND_HOST=127.0.0.1 \
    MCP_PORT=9102 \
    MCP_TRANSPORT=http

RUN groupadd --system --gid 10001 mcp \
    && useradd --system --uid 10001 --gid mcp --create-home --home-dir /app mcp

# CI supplies exactly one wheel built and smoke-tested in the exact-wheel job.
COPY dist/*.whl /tmp/dist/
RUN test "$(find /tmp/dist -maxdepth 1 -name '*.whl' | wc -l)" -eq 1 \
    && python -m pip install /tmp/dist/*.whl \
    && rm -rf /tmp/dist

WORKDIR /app
RUN install -d -o mcp -g mcp -m 0700 /app/data /app/data/artifacts
USER 10001:10001

EXPOSE 9102
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9102/health', timeout=2).read()" || exit 1

ENTRYPOINT ["local-home-devices-mcp"]
