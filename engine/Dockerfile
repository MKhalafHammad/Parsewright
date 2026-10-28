# Parsewright engine: the API and its worker pool (`parsewright serve`).
# Non-root, slim, no Docker socket (threat T7.5): the engine reaches Splunk over REST only.
# Digest pinning is planned with the judges' setup (Phase 10, threat T9.3).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml ./
COPY parsewright ./parsewright
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --home-dir /app parsewright \
    # The packages folder must be owned by the engine user and not group/world-writable
    # (T5.9); Splunk reads it read-only through the shared volume.
    && install -d -o parsewright -g parsewright -m 0755 /opt/parsewright/packages \
    && install -d -o parsewright -g parsewright -m 0700 /app/.runs

USER parsewright
ENV PARSEWRIGHT_PACKAGES_DIR=/opt/parsewright/packages PARSEWRIGHT_RUNS_DIR=/app/.runs
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"
# The engine container is reached as "engine" on the compose network.
CMD ["parsewright", "--env-file", "/dev/null", "serve", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
