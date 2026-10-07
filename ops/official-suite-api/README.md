# Inactive official API image

This local artifact packages the official ASGI entry and matching compatibility API wheel from one stable checkout. It does not activate an official service or join production compose/release. The existing [API composition contract](../../apps/official-suite/api/README.md) still closes business HTTP with 503 and WebSockets with 1013. `/healthz` reports `activation: inactive`; `/readyz` remains 503. Health is not readiness or writer ownership.

The Dockerfile uses the same pinned Python 3.12, Node 22 and uv images as `ops/app/Dockerfile`, with `apps/api/uv.lock` and the root pnpm lock. It installs both checkout wheels with `--no-deps`. The existing API dependency lock still includes OPF/torch and produces a large dependency layer. Splitting that lock is separate dependency/source work. OS packages and the existing isolated wheel build backend follow the existing app build policy; this is not a claim of byte-for-byte reproducibility across future package repository changes.

Only explicit source/resource paths enter the image. The runtime contains installed Python wheels, existing non-secret runtime configuration, the workspace marker needed by settings/resource lookup, desktop update metadata required by imports, and the real Node/BlockNote/Yjs codec. It contains no API source checkout, worker, migration tree, web frontend, `.env`, credentials or runtime data. The API wheel itself still contains common and business code; a container boundary does not complete source or database isolation.

Build only after other writers have stabilized the shared API source. The context command freezes only the explicit input paths into a tar archive before Docker starts, and rejects changes observed while copying. It never reads host environment or credential files. The input file inventory/digest, base digests, two wheel digests, checkout revision and explicit dirty flag are recorded in `/opt/miy/artifact.json`; image labels also record revision/dirty/inactive status. A dirty build is local evidence, not a release revision or deployment approval.

Input inventory and every content read walk from a canonical root using directory file descriptors and `O_NOFOLLOW` for each path component. Root/ancestor/descendant symlinks, hardlinked files and non-regular files are rejected; `.env*` and `.auth_info*` inputs are refused, while Python bytecode caches are omitted. A previously accepted inventory does not authorize a replaced path. Reads check file identity before and after reading and compare the current path again, and context creation rechecks the complete file inventory/content hashes. Output creation also refuses symlink ancestors and existing archives. These checks use the Linux filesystem interfaces of the core build environment.

From a stable repository checkout:

```bash
official_api_revision=$(git rev-parse HEAD)
official_api_dirty=false
if test -n "$(git status --porcelain)"; then official_api_dirty=true; fi
python ops/official-suite-api/verify.py context \
  --output .runtime/official-api-artifact/context.tar
docker build --file ops/official-suite-api/Dockerfile \
  --build-arg MIY_BUILD_REVISION="$official_api_revision" \
  --build-arg MIY_BUILD_SOURCE_DIRTY="$official_api_dirty" \
  --tag miy-official-api:local-inactive - < .runtime/official-api-artifact/context.tar
official_api_image=$(docker image inspect --format '{{.Id}}' miy-official-api:local-inactive)
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --entrypoint apps/api/.venv/bin/python "$official_api_image" \
  ops/official-suite-api/verify.py verify
```

Use a new archive path on repeat runs: the context command refuses to overwrite an existing artifact. If context creation fails or is interrupted, do not build from that partial archive. The context command's `input_sha256` must equal the image check's `input_sha256`; record the immutable image ID and verification output with the local evidence.

The check is a one-process ASGI inspection, with no listener, published port, mounts, host env file or database. It runs as UID 10001, imports the installed wheels, checks config/resource hashes, blocks outbound socket connections and forbidden runtime initialization, checks health/readiness/OpenAPI/business HTTP/WebSocket closure, and roundtrips content through the actual codec. Its only DSN is a synthetic unreachable address supplied inside the verifier to satisfy the unchanged typed configuration contract. The image command itself still requires typed runtime settings; no default database credential or activation switch is added.

No production release labels, Compose entries, queue consumers or migrator are created here. Service activation still requires the [writer/routing/identity/database cutover](../../platform-redesign/OFFICIAL_API_CUTOVER.md). Do not use the local tag or the health endpoint as evidence that this cutover is complete.

Local validation on 2026-10-06 built and inspected the `linux/amd64` image `sha256:4b85f5d74cb8f5b85e833aeeb3bff6d83f45982325f5ca270bacb92766da8c1e` (7,306,092,984 bytes). Its source revision is `449d1417afbf6a2eb978c1465c765e26ef43c5dc`, explicitly `source_dirty: true`. The frozen context and image both report input digest `011fffc42c0d5c710a32159bd96cef94623b67a1070993a70441e1cad7dccefd`. The network-disabled, read-only, UID 10001 verifier passed installed-wheel imports, unchanged inactive health/readiness and HTTP/WebSocket boundaries, OpenAPI ownership and real codec roundtrip. The named one-shot container was removed by `--rm`; no listener or service was started. Local metadata and logs are retained under `.runtime/official-api-artifact/20261006T201239Z/`. This records that exact frozen input set, not subsequent checkout changes or production validation.

The later input-boundary review checked all 731 regular entries in that retained archive, found no excluded environment/auth/runtime paths and recomputed both matching archive/input digests. The path-opening hardening described above was added **after** that image was built. Its pure temporary-filesystem regressions run with `python3 -m unittest scripts.tests.test_official_api_artifact` and cover ancestor links, hardlinks, special files, replacements, changing inputs and unreusable partial archives. That earlier image does not cover the newer helper; the final frozen validation below does.

The hardened helper passed all 13 temporary-filesystem tests and a complete 732-file context check on 2026-10-06. That later context's input digest is `225e59f1c48cd1c0b93057f9e760afb52f13ad69774635168fcfec95a2aa7c37`; evidence is under `.runtime/official-api-artifact/20261006T203314000197Z-hardened-context/`. The checkout's existing public `packages/contracts/miy-desktop-update-feed.manifest.json` had two hardlinks and was replaced at that workspace path by a byte-identical, same-mode regular file. Its SHA-256 remains `07990f03b89d2f77a23ef85920e21b30dfba949fe9f22045d03e172aa31d7632`, link count is now one, and Git reports no content change. No other link was opened, located or removed. No Docker image was built from this later validation context.


## Final frozen backend validation

After the Docs relay/SQL deadline, official authority isolation and restricted writer-role changes stabilized, the hardened helper froze **732 input files** and built a new `linux/amd64` image. The helper's 13 temporary-filesystem tests passed before freezing. The actual build completed in 156.75 seconds using the unchanged immutable bases and frozen locks; the read-only, network-disabled one-shot verification passed in 9.28 seconds. Rechecking the checkout's explicit input files after verification produced the same input digest.

| Evidence | Value |
| --- | --- |
| Immutable image | `sha256:6477bb67153c51b239507e776d4ed39b85293a3e76da05579efadd49981ca54d` |
| Local tag | `miy-official-api:local-inactive-20261006t205748654559z-final` |
| Image size | `7306138770` bytes (about 7.31 GB) |
| Checkout revision | `449d1417afbf6a2eb978c1465c765e26ef43c5dc` |
| Source dirty | `true` |
| Frozen context SHA-256 | `4141d76ac9818174d8661e202bc8e669b2b31cf1eaa56522fd3194f69ad7246b` |
| Input inventory SHA-256 | `cf75e78d137a77711076682a8aee343181d26c80e35012be0d53e243b18b492a` |
| `miy_api-0.1.1-py3-none-any.whl` SHA-256 | `c35b3bd8fe5c44091885402cd64be8bdaf6d19cbb7d63215149c4219919e68a5` |
| `miy_official_api-0.1.1-py3-none-any.whl` SHA-256 | `1c6c42eceeeb0313de322fff0d6f884a35309c48ad62cd304da9a4cf8196a491` |

The installed wheels, packaged resources/workspace marker, inactive health/readiness, HTTP 503/WS 1013 boundaries, official OpenAPI ownership and actual Node/BlockNote/Yjs roundtrip all passed. The verifier ran as UID 10001 with no network, a read-only filesystem, dropped capabilities, no-new-privileges, a 64 MB temporary filesystem, 256 PID limit and 2 GB memory limit. Container `miy-official-api-verify-20261006t205748654559z-final` was removed by `--rm`, and absence was verified. No listener, service, database connection, migration or deployment was started.

Evidence is retained under `.runtime/official-api-artifact/20261006T205748654559Z-final/`: `source.json`, `build-result.json`, `image.json`, `verify-result.json`, `post-build-input-check.json`, the frozen archive and bounded build/verification logs. The previous image `sha256:4b85f5d74cb8f5b85e833aeeb3bff6d83f45982325f5ca270bacb92766da8c1e` and its existing `miy-official-api:artifact-20261006t201239z` tag remain present. No existing cache, image or unrelated container was removed. The full API dependency lock remains large; this result is local inactive-artifact evidence, not production validation or a completed service/data/credential cutover.
