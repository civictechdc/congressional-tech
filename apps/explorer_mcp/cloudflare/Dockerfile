FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    CONGRESS_MCP_DATA_DIR=/data PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --create-home congress \
    && mkdir /data && chown congress:congress /data
COPY cloudflare/start.sh /app/start.sh
USER congress
EXPOSE 8080
ENTRYPOINT ["sh", "/app/start.sh"]
