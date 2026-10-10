# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579

FROM ${NODE_IMAGE} AS web-build
LABEL io.miy.build-cache="true"

WORKDIR /opt/miy

RUN corepack enable \
  && corepack prepare pnpm@10.34.5 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml nx.json tsconfig.base.json ./
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/collab-codec-runtime/package.json packages/collab-codec-runtime/package.json
COPY packages/core-web/package.json packages/core-web/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN pnpm install --frozen-lockfile
RUN pnpm --filter @miy/collab-codec-runtime deploy \
    --prod --legacy /opt/collab-codec-runtime

COPY . .
ARG MIY_BENTO_SERVER_URL
RUN test -n "${MIY_BENTO_SERVER_URL}" \
  && MIY_BENTO_SERVER_URL="${MIY_BENTO_SERVER_URL}" \
    NODE_OPTIONS=--max-old-space-size=3072 \
    pnpm nx build web --skip-nx-cache
RUN MIY_BENTO_SERVER_URL="${MIY_BENTO_SERVER_URL}" \
    NODE_OPTIONS=--max-old-space-size=3072 \
    pnpm nx build official-suite --skip-nx-cache \
  && if test -f dist/apps/web/.miy-build-id; then \
       cp dist/apps/web/.miy-build-id dist/apps/official-suite/.miy-platform-build-id; \
     else \
       printf '\n' > dist/apps/official-suite/.miy-platform-build-id; \
     fi

FROM ${PYTHON_IMAGE} AS python-build
LABEL io.miy.build-cache="true"

COPY --from=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823 /uv /usr/local/bin/uv

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/miy

COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md apps/api/
COPY apps/worker/pyproject.toml apps/worker/uv.lock apps/worker/README.md apps/worker/
RUN UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/api \
  && UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/worker

# Keep the multi-gigabyte third-party environments independent of app source.
# Build only the small application wheels after source changes.
FROM python-build AS python-packages
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
COPY apps/official-suite/api/pyproject.toml apps/official-suite/api/README.md apps/official-suite/api/
COPY apps/official-suite/api/src apps/official-suite/api/src
COPY apps/official-suite/worker/pyproject.toml apps/official-suite/worker/README.md apps/official-suite/worker/
COPY apps/official-suite/worker/src apps/official-suite/worker/src
RUN uv build --no-cache --wheel --out-dir /wheels --directory apps/api \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/worker \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/official-suite/api \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/official-suite/worker

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libstdc++6 poppler-utils librsvg2-bin nginx-light \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 miy \
  && useradd --uid 10001 --gid miy --create-home --home-dir /opt/miy miy

WORKDIR /opt/miy

COPY --from=python-build /opt/miy/apps/api/.venv apps/api/.venv
COPY --from=python-build /opt/miy/apps/worker/.venv apps/worker/.venv
COPY --chown=miy:miy apps/api/src apps/api/src
COPY --chown=miy:miy apps/api/alembic apps/api/alembic
COPY --chown=miy:miy apps/api/alembic.ini apps/api/alembic.ini
COPY --chown=miy:miy apps/worker/src apps/worker/src
RUN --mount=type=bind,from=python-build,source=/usr/local/bin/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=python-packages,source=/wheels,target=/wheels \
    uv pip install --no-cache --no-deps --python apps/api/.venv/bin/python \
      /wheels/miy_api-*.whl /wheels/miy_official_api-*.whl \
  && uv pip install --no-cache --no-deps --python apps/worker/.venv/bin/python \
      /wheels/miy_api-*.whl /wheels/miy_worker-*.whl /wheels/miy_official_worker-*.whl
COPY --chown=miy:miy pnpm-workspace.yaml pnpm-workspace.yaml
COPY --chown=miy:miy config config
COPY --chown=miy:miy ops/first-party/gateway.py ops/first-party/gateway.py
COPY --chown=miy:miy packages/contracts/miy-desktop-update-feed.manifest.json packages/contracts/miy-desktop-update-feed.manifest.json
COPY --chown=miy:miy scripts/blocknote-collab-codec.mjs scripts/blocknote-collab-codec.mjs
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY --from=web-build --chown=miy:miy /opt/collab-codec-runtime/node_modules node_modules
COPY --from=web-build --chown=miy:miy /opt/miy/dist/apps/web dist/apps/web
COPY --from=web-build --chown=miy:miy /opt/miy/dist/apps/official-suite dist/apps/official-suite

RUN mkdir -p .runtime/opf-cache .runtime/recording-spool \
  && chown -R miy:miy .runtime

USER miy

# Revision metadata must not invalidate dependency copies or OS package layers.
ARG MIY_BUILD_REVISION=unmanaged
ARG MIY_RELEASE_CONTRACT=unmanaged
ARG MIY_RELEASE_SOURCE_REVISION=unmanaged
ARG MIY_RELEASE_TREE=unmanaged
ARG MIY_RELEASE_PLATFORM=unmanaged
ARG MIY_RELEASE_BENTO_URL_SHA256=unmanaged
ARG MIY_RELEASE_MR=unmanaged
ARG MIY_RELEASE_PIPELINE=unmanaged
LABEL org.opencontainers.image.title="miy" \
  org.opencontainers.image.revision="${MIY_BUILD_REVISION}" \
  io.miy.release.contract="${MIY_RELEASE_CONTRACT}" \
  io.miy.release.source-revision="${MIY_RELEASE_SOURCE_REVISION}" \
  io.miy.release.tree="${MIY_RELEASE_TREE}" \
  io.miy.release.platform="${MIY_RELEASE_PLATFORM}" \
  io.miy.release.bento-url-sha256="${MIY_RELEASE_BENTO_URL_SHA256}" \
  io.miy.release.merge-request="${MIY_RELEASE_MR}" \
  io.miy.release.pipeline="${MIY_RELEASE_PIPELINE}"
ENV MIY_RUNTIME_REVISION="${MIY_BUILD_REVISION}"

CMD ["apps/api/.venv/bin/uvicorn", "miy_api.main:app", "--app-dir", "apps/api/src", "--host", "127.0.0.1", "--port", "8000"]
