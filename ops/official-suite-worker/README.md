# Inactive worker profile wheels

## First-party service image

The [Dockerfile](Dockerfile) builds a separate official consumer image from the
existing pinned Python/Node/uv bases and frozen `apps/worker/uv.lock`. It installs
matching `miy-api`, `miy-worker` and `miy-official-worker` wheels from one checkout
with `--no-deps`; the four business task implementations are owned by the official
worker wheel, and the legacy module names are thin aliases of those same objects.
The legacy app image also installs that matching owner wheel so compatibility
imports keep working during transition and rollback.

The image imports installed wheels, includes the common non-secret runtime
resources and actual collaboration codec, and runs as UID/GID 10001. Its command
is `miy_official_worker.runtime:celery_app`; the native Celery app supplies its
generated official queue inventory. It creates no Beat and has no migrations,
source checkout, frontend or app credentials. Existing third-party dependencies
are unchanged. The guarded release supplies immutable source/tree/contract labels
and the normal typed runtime configuration. Building the image does not deploy
it or grant it database/broker authority.

The single Beat remains `miy_worker.first_party_beat:celery_app` in the platform
image and uses the same official task wheel for its compatibility registrations.
Retire old consumers and verify exactly one Beat before switching publishers.
The offline inspection below remains inactive and checks wheel origins, matching
versions, normal runtime entry availability and owner/alias identity without
starting consumers or importing active runtime entries. Actual queue consumption,
readiness, task execution and shutdown are verified together at the final cutover.

This local-only artifact consists of matching `miy-api`, `miy-worker` and
`miy-official-worker` wheels. The existing worker lock owns dependencies. No
service image, Compose/systemd entry, queue consumer, Beat process, operational
setting or production release is installed by this recipe.

Wait for the matching API/worker inputs to stop changing and use a new owned
output directory. Record source hashes before/after all three builds. From the
repository root, with `<output>` replaced by that new absolute directory:

```bash
uv build --offline --wheel --directory apps/api --out-dir <output>
uv build --offline --wheel --directory apps/worker --out-dir <output>
uv build --offline --wheel --directory apps/official-suite/worker --out-dir <output>
apps/worker/.venv/bin/python ops/official-suite-worker/verify.py <output>
```

The verifier uses the existing locked dependency environment. Python loads each
supplied wheel directly in a fresh interpreter, and the verifier checks that
every imported MIY API/worker module actually came from those wheels. It rejects
host environment-file reads, outbound sockets, runtime DB/extension bootstrap,
unowned task registration and attempted worker/Beat/publication/direct or eager
task execution. It records wheel digests, profile task/Beat counts and disjoint
queue inventories. No application function or broker listener is run. This is
not a dependency-isolated image, an operational worker or a broker ACL proof.

The profile registrations preserve task IDs and legacy options; the original
legacy entry remains active and unchanged by these artifacts. Its tests still
exercise existing user admission, attempt/lease and compensation behavior. See
the [worker owner](../../apps/worker/README.md) for the deliberately unresolved
activation contracts. Package inspection never authorizes running two consumers
on the shared legacy `celery` queue.
