# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579

FROM ${NODE_IMAGE} AS web-build
LABEL io.mty.build-cache="true"

WORKDIR /opt/mty

RUN corepack enable \
  && corepack prepare pnpm@10.34.5 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml nx.json tsconfig.base.json ./
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/collab-codec-runtime/package.json packages/collab-codec-runtime/package.json
COPY packages/core-web/package.json packages/core-web/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN pnpm install --frozen-lockfile

COPY . .
ARG MTY_BENTO_SERVER_URL
RUN test -n "${MTY_BENTO_SERVER_URL}" \
  && MTY_BENTO_SERVER_URL="${MTY_BENTO_SERVER_URL}" \
    NODE_OPTIONS=--max-old-space-size=3072 \
    pnpm nx build web --skip-nx-cache
RUN pnpm --filter @mty/collab-codec-runtime deploy \
    --prod --legacy /opt/collab-codec-runtime

FROM ${PYTHON_IMAGE} AS python-build
LABEL io.mty.build-cache="true"

COPY --from=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 /uv /usr/local/bin/uv

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/mty

COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md apps/api/
COPY apps/worker/pyproject.toml apps/worker/uv.lock apps/worker/README.md apps/worker/
RUN UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/api \
  && UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/worker

COPY apps/api/src apps/api/src
COPY apps/api/alembic apps/api/alembic
COPY apps/api/alembic.ini apps/api/alembic.ini
COPY apps/worker/src apps/worker/src
RUN UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-editable --directory apps/api \
  && UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-editable --directory apps/worker

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libstdc++6 poppler-utils librsvg2-bin \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 mty \
  && useradd --uid 10001 --gid mty --create-home --home-dir /opt/mty mty

WORKDIR /opt/mty

COPY --from=python-build /opt/mty/apps/api/.venv apps/api/.venv
COPY --from=python-build /opt/mty/apps/worker/.venv apps/worker/.venv
COPY --chown=mty:mty apps/api/src apps/api/src
COPY --chown=mty:mty apps/api/alembic apps/api/alembic
COPY --chown=mty:mty apps/api/alembic.ini apps/api/alembic.ini
COPY --chown=mty:mty apps/worker/src apps/worker/src
COPY --chown=mty:mty pnpm-workspace.yaml pnpm-workspace.yaml
COPY --chown=mty:mty packages/contracts/mty-desktop-update-feed.manifest.json packages/contracts/mty-desktop-update-feed.manifest.json
COPY --chown=mty:mty scripts/blocknote-collab-codec.mjs scripts/blocknote-collab-codec.mjs
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY --from=web-build --chown=mty:mty /opt/collab-codec-runtime/node_modules node_modules
COPY --from=web-build --chown=mty:mty /opt/mty/dist/apps/web dist/apps/web

RUN mkdir -p .runtime/opf-cache .runtime/recording-spool \
  && chown -R mty:mty .runtime

USER mty

# Revision metadata must not invalidate dependency copies or OS package layers.
ARG MTY_BUILD_REVISION=unmanaged
LABEL org.opencontainers.image.title="MTY" \
  org.opencontainers.image.revision="${MTY_BUILD_REVISION}"
ENV MTY_RUNTIME_REVISION="${MTY_BUILD_REVISION}"

CMD ["apps/api/.venv/bin/uvicorn", "mty_api.main:app", "--app-dir", "apps/api/src", "--host", "127.0.0.1", "--port", "8000"]
