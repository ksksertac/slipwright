# Slipwright: API + web UI + the toolchains the agents need to build the projects they
# work on (git, gh, uv/Python, Node). State (SQLite, secret key, clones, worktrees, logs)
# lives under /data — mount a volume there.
#
#   docker compose up --build
#   docker compose exec slipwright slipwright user add ada
#
# Stage 1: build the web UI ----------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY schemas/openapi.json /src/schemas/openapi.json
COPY web/ ./
# vite writes to ../slipwright/api/static (see vite.config.ts)
RUN mkdir -p /src/slipwright/api && npm run build

# Stage 2: runtime --------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:/root/.local/bin:${PATH}" \
    SLIPWRIGHT_STATE_DIR=/data \
    SLIPWRIGHT_HOST=0.0.0.0 \
    SLIPWRIGHT_PORT=8500

# git + gh (DevOps role), curl (health checks), node (projects that need it)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gnupg openssh-client \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
         > /etc/apt/sources.list.d/github-cli.list \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv: runs Slipwright and is the package manager of the example (Python) profile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
# dependencies first so source edits do not invalidate this layer
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY slipwright/ ./slipwright/
COPY examples/ ./examples/
COPY schemas/ ./schemas/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
COPY --from=web /src/slipwright/api/static ./slipwright/api/static

# jobs commit on their branches; give git an identity so commits never fail
RUN git config --global user.name slipwright \
    && git config --global user.email slipwright@localhost \
    && git config --global --add safe.directory '*'

VOLUME ["/data"]
EXPOSE 8500
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://127.0.0.1:8500/healthz || exit 1

ENTRYPOINT ["slipwright"]
CMD ["serve"]
