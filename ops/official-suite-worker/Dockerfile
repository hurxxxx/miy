# syntax=docker/dockerfile:1.7

# Reuse the existing immutable toolchain and worker dependency lock.
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

FROM ${PYTHON_IMAGE} AS dependencies
LABEL io.miy.build-cache="true"
COPY --from=uv-toolchain /uv /usr/local/bin/uv
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates git \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/miy
COPY apps/worker/pyproject.toml apps/worker/uv.lock apps/worker/README.md apps/worker/
RUN UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    uv sync --no-cache --frozen --no-dev --no-install-project --directory apps/worker

FROM dependencies AS wheels
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
COPY apps/api/src apps/api/src
COPY apps/worker/src apps/worker/src
COPY apps/official-suite/worker/pyproject.toml apps/official-suite/worker/README.md apps/official-suite/worker/
COPY apps/official-suite/worker/src apps/official-suite/worker/src
RUN uv build --no-cache --wheel --out-dir /wheels --directory apps/api \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/worker \
  && uv build --no-cache --wheel --out-dir /wheels --directory apps/official-suite/worker

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates libstdc++6 poppler-utils librsvg2-bin \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 10001 miy \
  && useradd --uid 10001 --gid miy --create-home --home-dir /opt/miy miy
WORKDIR /opt/miy
COPY --from=dependencies /opt/miy/apps/worker/.venv apps/worker/.venv
RUN --mount=type=bind,from=uv-toolchain,source=/uv,target=/usr/local/bin/uv \
    --mount=type=bind,from=wheels,source=/wheels,target=/wheels \
    uv pip install --no-cache --no-deps --python apps/worker/.venv/bin/python \
      /wheels/miy_api-*.whl /wheels/miy_worker-*.whl /wheels/miy_official_worker-*.whl
COPY pnpm-workspace.yaml pnpm-workspace.yaml
COPY config/runtime.json config/runtime.schema.json config/
COPY packages/contracts/miy-desktop-update-feed.manifest.json packages/contracts/miy-desktop-update-feed.manifest.json
COPY scripts/blocknote-collab-codec.mjs scripts/blocknote-collab-codec.mjs
COPY --from=codec /usr/local/bin/node /usr/local/bin/node
COPY --from=codec /opt/collab-codec-runtime/node_modules node_modules
RUN mkdir -p .runtime/opf-cache .runtime/recording-spool \
  && chown -R miy:miy .runtime
USER miy

ARG MIY_BUILD_REVISION=unmanaged
ARG MIY_BUILD_SOURCE_DIRTY=true
ARG MIY_RELEASE_CONTRACT=unmanaged
ARG MIY_RELEASE_SOURCE_REVISION=unmanaged
ARG MIY_RELEASE_TREE=unmanaged
ARG MIY_RELEASE_PLATFORM=unmanaged
ARG MIY_RELEASE_BENTO_URL_SHA256=unmanaged
ARG MIY_RELEASE_MR=unmanaged
ARG MIY_RELEASE_PIPELINE=unmanaged
LABEL org.opencontainers.image.title="miy-official-worker" \
  org.opencontainers.image.revision="${MIY_BUILD_REVISION}" \
  io.miy.artifact.source-dirty="${MIY_BUILD_SOURCE_DIRTY}" \
  io.miy.artifact.activation="first-party-runtime" \
  io.miy.release.contract="${MIY_RELEASE_CONTRACT}" \
  io.miy.release.source-revision="${MIY_RELEASE_SOURCE_REVISION}" \
  io.miy.release.tree="${MIY_RELEASE_TREE}" \
  io.miy.release.platform="${MIY_RELEASE_PLATFORM}" \
  io.miy.release.bento-url-sha256="${MIY_RELEASE_BENTO_URL_SHA256}" \
  io.miy.release.merge-request="${MIY_RELEASE_MR}" \
  io.miy.release.pipeline="${MIY_RELEASE_PIPELINE}"
ENV MIY_RUNTIME_REVISION="${MIY_BUILD_REVISION}"
# The native app's generated owned queue inventory supplies the subscription set.
CMD ["apps/worker/.venv/bin/celery", "-A", "miy_official_worker.runtime:celery_app", "worker", "--loglevel=INFO"]
