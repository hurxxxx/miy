# syntax=docker/dockerfile:1.7

# Match the existing app artifact's pinned toolchain and frozen runtime locks.
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.3@sha256:90bbb3c16635e9627f49eec6539f956d70746c409209041800a0280b93152823

FROM ${UV_IMAGE} AS uv-toolchain

FROM ${NODE_IMAGE} AS codec
LABEL io.miy.build-cache="true"
WORKDIR /opt/miy
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/collab-codec-runtime/package.json packages/collab-codec-runtime/package.json
COPY packages/core-web/package.json packages/core-web/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN pnpm install --frozen-lockfile \
  && pnpm --filter @miy/collab-codec-runtime deploy --prod --legacy /opt/collab-codec-runtime

FROM codec AS official-web-build
# The service target uses the same reviewed source tree as the release contract.
# The existing API-only context/verifier remains valid for the inactive target.
COPY . .
ARG MIY_BENTO_SERVER_URL
ARG MIY_PLATFORM_WEB_BUILD_ID=
RUN test -n "${MIY_BENTO_SERVER_URL}" \
  && MIY_BENTO_SERVER_URL="${MIY_BENTO_SERVER_URL}" \
    MIY_PLATFORM_WEB_BUILD_ID="${MIY_PLATFORM_WEB_BUILD_ID}" \
    NODE_OPTIONS=--max-old-space-size=3072 \
    pnpm nx build official-suite --skip-nx-cache

FROM ${PYTHON_IMAGE} AS dependencies
LABEL io.miy.build-cache="true"
COPY --from=uv-toolchain /uv /usr/local/bin/uv
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/miy
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md apps/api/
RUN UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/api

FROM dependencies AS wheels
COPY apps/api/src apps/api/src
COPY apps/official-suite/api/pyproject.toml apps/official-suite/api/README.md apps/official-suite/api/
COPY apps/official-suite/api/src apps/official-suite/api/src
RUN uv build --no-cache --wheel --out-dir /wheels --directory apps/api \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/official-suite/api

# Explicit build inputs only: no checkout, .env, auth files or runtime state.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/contracts/package.json packages/contracts/package.json
COPY packages/collab-codec-runtime/package.json packages/collab-codec-runtime/package.json
COPY packages/core-web/package.json packages/core-web/package.json
COPY packages/ui/package.json packages/ui/package.json
COPY config/runtime.json config/runtime.schema.json config/
COPY packages/contracts/miy-desktop-update-feed.manifest.json packages/contracts/miy-desktop-update-feed.manifest.json
COPY scripts/blocknote-collab-codec.mjs scripts/blocknote-collab-codec.mjs
COPY ops/official-suite-api/Dockerfile ops/official-suite-api/verify.py ops/official-suite-api/
ARG NODE_IMAGE
ARG PYTHON_IMAGE
ARG UV_IMAGE
ARG MIY_BUILD_REVISION
ARG MIY_BUILD_SOURCE_DIRTY
RUN python ops/official-suite-api/verify.py record \
    --revision "${MIY_BUILD_REVISION}" --dirty "${MIY_BUILD_SOURCE_DIRTY}" \
    --node-image "${NODE_IMAGE}" --python-image "${PYTHON_IMAGE}" --uv-image "${UV_IMAGE}"

FROM ${PYTHON_IMAGE} AS inactive-runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libstdc++6 poppler-utils librsvg2-bin \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 miy \
  && useradd --uid 10001 --gid miy --create-home --home-dir /opt/miy miy
WORKDIR /opt/miy
COPY --from=dependencies /opt/miy/apps/api/.venv apps/api/.venv
RUN --mount=type=bind,from=uv-toolchain,source=/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    uv pip install --no-cache --no-deps --python apps/api/.venv/bin/python \
      /wheels/miy_api-*.whl /wheels/miy_official_api-*.whl \
  && apps/api/.venv/bin/python -m miy_api.first_party_routes --json >/dev/null
COPY --from=wheels /opt/miy/pnpm-workspace.yaml pnpm-workspace.yaml
COPY --from=wheels /opt/miy/config config
COPY --from=wheels /opt/miy/packages/contracts/miy-desktop-update-feed.manifest.json packages/contracts/miy-desktop-update-feed.manifest.json
COPY --from=wheels /opt/miy/scripts/blocknote-collab-codec.mjs scripts/blocknote-collab-codec.mjs
COPY --from=wheels /opt/miy/ops/official-suite-api/verify.py ops/official-suite-api/verify.py
COPY --from=wheels /opt/miy/artifact.json artifact.json
COPY --from=codec /usr/local/bin/node /usr/local/bin/node
COPY --from=codec /opt/collab-codec-runtime/node_modules node_modules
USER miy
ARG MIY_BUILD_REVISION
ARG MIY_BUILD_SOURCE_DIRTY
LABEL org.opencontainers.image.title="miy-official-api-inactive" \
  org.opencontainers.image.revision="${MIY_BUILD_REVISION}" \
  io.miy.artifact.source-dirty="${MIY_BUILD_SOURCE_DIRTY}" \
  io.miy.artifact.activation="inactive"
ENV MIY_RUNTIME_REVISION="${MIY_BUILD_REVISION}"
CMD ["apps/api/.venv/bin/uvicorn", "miy_official_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Service activation is an explicit compose/release choice; the default image below
# retains the offline inactive composition and its original verification contract.
FROM inactive-runtime AS service-runtime
COPY --from=official-web-build --chown=miy:miy /opt/miy/dist/apps/official-suite dist/apps/official-suite
ARG MIY_RELEASE_CONTRACT=unmanaged
ARG MIY_RELEASE_SOURCE_REVISION=unmanaged
ARG MIY_RELEASE_TREE=unmanaged
ARG MIY_RELEASE_PLATFORM=unmanaged
ARG MIY_RELEASE_BENTO_URL_SHA256=unmanaged
ARG MIY_RELEASE_MR=unmanaged
ARG MIY_RELEASE_PIPELINE=unmanaged
LABEL org.opencontainers.image.title="miy-official-api" \
  io.miy.artifact.activation="first-party-runtime" \
  io.miy.release.contract="${MIY_RELEASE_CONTRACT}" \
  io.miy.release.source-revision="${MIY_RELEASE_SOURCE_REVISION}" \
  io.miy.release.tree="${MIY_RELEASE_TREE}" \
  io.miy.release.platform="${MIY_RELEASE_PLATFORM}" \
  io.miy.release.bento-url-sha256="${MIY_RELEASE_BENTO_URL_SHA256}" \
  io.miy.release.merge-request="${MIY_RELEASE_MR}" \
  io.miy.release.pipeline="${MIY_RELEASE_PIPELINE}"
CMD ["apps/api/.venv/bin/uvicorn", "miy_official_api.runtime:app", "--host", "0.0.0.0", "--port", "8000"]

FROM inactive-runtime AS runtime
