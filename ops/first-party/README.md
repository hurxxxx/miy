# First-party service migration

This topology runs the platform and the official app suite in separate UI
artifacts, API and worker processes. A platform-owned local NGINX gateway retains
the existing public service port. One shared Beat retains the existing schedule. Personal app
containers and Workbench keep their separate runtime and release owners.

The existing PostgreSQL schema, source transactions, resource ACL and fixed
`legacy` writer identity are reused by trusted first-party services. The older
delegated Source-only artifacts remain inactive. These entries do not prepare
new roles, adopt another writer generation, run migrations or seed data.

The guarded `prod-app.sh --topology first-party` path manages six services using
three immutable application artifacts. The default remains legacy. Loading a
Compose example alone is not a guarded release or evidence of a completed
cutover; the image/review/CI and rollback contract covers the complete service
inventory before activation.

Once a split runtime exists, every mutating command must explicitly select
`--topology first-party`. Omitting it holds before image promotion, service
changes or migrations. The same inspection rejects leftover split services
without a known owned worker. A coordinated full split release still supports
legacy-to-split drain, and paired split-to-legacy recovery uses the explicit
first-party current topology with its pinned legacy rollback bundle.

| Owner                                      | Entry                                         | Artifact                                                     |
| ------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------ |
| Public service routing                     | `ops/first-party/gateway.py` and native NGINX | Platform image                                               |
| Platform HTTP and common realtime          | `miy_api.platform_runtime:app`                | `ops/app/Dockerfile`                                         |
| Official HTTP and Docs/Whiteboard realtime | `miy_official_api.runtime:app`                | `ops/official-suite-api/Dockerfile --target service-runtime` |
| Platform jobs                              | `miy_worker.first_party_platform:celery_app`  | Platform image                                               |
| Official jobs                              | `miy_official_worker.runtime:celery_app`      | `ops/official-suite-worker/Dockerfile`                       |
| Shared schedule                            | `miy_worker.first_party_beat:celery_app`      | Platform image                                               |

The official artifact contains a matching common compatibility wheel. Changing
an official business handler therefore rebuilds that wheel in the official
artifact, but does not require replacing the running platform image. Changes to
shared database schema or public platform contracts still require impact-based
coordination. Changes consumed by the portal, including shared manifests,
summary clients and build inputs, also require a coordinated full release.
Physical extraction of the remaining API compatibility sources is
a later improvement, not a claim made by the process split.

## Routing

The gateway listens on the existing `MIY_APP_BIND_HOST` and `MIY_APP_PORT`, so the
current HTTPS connection to that port does not need another path map. The
platform API moves to `127.0.0.1:18779`; the official service uses
`127.0.0.1:18780`. Both internal ports must be free before the transition. The
gateway receives only listener/prefix/trusted-proxy configuration, no application
secrets or runtime storage. It derives both owner maps from its reviewed image.
Only the configured external peers may supply a forwarded scheme or client IP;
the internal APIs trust the loopback gateway. Arbitrary client headers do not
create proxy trust.

`gateway.py --print-config` prints the same validated NGINX configuration without
starting a service. It reads the reviewed wheel's generated route metadata and
requires only the four public gateway settings, with no application or database
configuration. The existing OpenAPI generator owns metadata generation and
drift checks. Default startup writes a private configuration before native exec;
`--check` separately probes the fixed local health routes.

For an operator-managed direct NGINX front door, the optional TLS example can
also consume those maps. It is not required for the local gateway topology.
Generate both NGINX owner maps from the same reviewed router inventory and app
contracts as the images, using the exact configured API prefix:

```bash
apps/api/.venv/bin/python -m miy_api.first_party_routes --nginx-map --api-prefix /api/v1
apps/api/.venv/bin/python -m miy_api.first_party_routes --client-map
```

Save those outputs as the Core-owned API and client includes referenced by
`portal.nginx.conf.example`, set its platform upstream to `127.0.0.1:18779`, and
retain the portal's real domain, TLS and upload limits. The
example official upstream is `127.0.0.1:18780`; reserve the port before startup.
The official UI owns the existing generated `/apps/<official-id>` route bases,
`/official-suite/assets`, `/official-suite/widgets` and its fixed service-worker
and help assets. The public `/official-suite/healthz` and `/official-suite/readyz`
paths proxy the official process health directly. The read-only
`/official-suite/platform-build.json` reports artifact metadata for operations.
The same build input fixes the compatible platform ID in the official JavaScript
and its metadata file; browser startup uses the compiled value. Official releases
must match the actual platform ID, and old JavaScript retains its old identity
when server metadata changes. Existing stale-write and realtime guards remain.

The common realtime route stays with the platform; Docs and Whiteboard
WebSockets route to the official process. Authentication cookies and request
origins are preserved and both handlers enforce the existing server authority.
The proxy adds no delegated identity or access grants.

The portal compiles shared primitives and official metadata, while the official
artifact compiles business screens and the widget host. Navigating between the
two trusted documents retains existing URLs and the same-origin platform
session. The fixed widget document restores its own session; the parent sends
UI events only and observes panel bounds for pointer handling. It sends no token
or delegated app authority.

For development, the root launcher starts Vite4200 and official Vite4201 together.
After the normal legacy bootstrap and consumer are running,
`./dev.sh --first-party --restart` stops publishers, obtains native drain evidence
and starts platform API plus official development API18781 and two owned
consumers with one Beat. A successful transition records the selected topology
in owner-only local runtime state. A fully stopped server can restart that same
namespace directly; switching to another topology still requires live drain
evidence. Initial first-party startup without a prior selection or a known
consumer holds rather than treating missing inspect replies as an empty broker. The
API-only/web-only flags retain their narrower startup scope. Generated API owner
JSON controls both Vite proxies in first-party mode; the default mode continues
to use the legacy API.
Worker shutdown identifies the native Python Main by owner UID, exact worker
checkout cwd/interpreter/argv and parent relationships. It excludes shell/uv
wrappers and matching prefork descendants even without process-title support;
unavailable or ambiguous identity holds rather than signaling guessed PIDs.
Normal stop and same-namespace restart warm-TERM only consumer Mains and wait
for completion before API, UI and Beat cleanup. The launcher requires native
`setsid --wait` to isolate Nx from terminal signals while Bash handles shutdown;
managed execution must use Main-only signals and preserve the complete native
warm grace (`KillMode=process`, `SendSIGKILL=no`). These source changes do not
update an already running launcher's loaded cleanup code. Namespace changes
retain publisher-off fresh native drain before retiring the old consumers.

WebSocket upgrade forwarding and disabled response buffering use the
[NGINX WebSocket](https://nginx.org/en/docs/http/websocket.html) and
[proxy module](https://nginx.org/en/docs/http/ngx_http_proxy_module.html) contracts.

## One writer and one schedule during cutover

1. Retain the current image IDs, runtime definitions, configuration and DB backup.
   Review/CI and immutable release labels must cover each proposed artifact.
2. Stop public admission, the legacy API and the legacy Beat. Keep legacy workers running
   long enough to finish already published work. Do not start new publishers yet.
3. Confirm every legacy queue is empty and every expected legacy consumer reports
   no active, reserved or scheduled work, including ETA/retry tasks. Native Redis
   unacknowledged storage must also contain zero messages; unknown or inconsistent
   transport observations hold. Unknown
   consumer inventory, outstanding work or failed observation holds the cutover.
   Do not purge queues, copy opaque messages or reissue unconfirmed tasks.
4. Stop the drained legacy consumers. Start the platform and official consumers
   with the exact generated owned queue sets and start the single shared Beat.
   Start both APIs and the local gateway in the same guarded transition.
5. Verify readiness, current source/writer identity, representative authorized and
   denied requests, common and official realtime, and persisted content/recovery.
   Retain the prior topology until the rollback checks are accepted.

Task names, payloads, attempt/lease and retry behavior retain their existing
meaning. Existing pending database work is recovered by the current due-lease
recovery/republisher path. The queue drain is an operational prerequisite;
importing a factory does not observe or attest it. The generated owned queue
command is `python -m miy_worker.first_party_queues --profile platform|official`.

An official suite release changes its API/worker artifacts together while keeping
the platform API, gateway and shared schedule owner fixed unless a shared contract
changes. Never run the legacy combined consumer or another Beat alongside the
new owned consumers. Workbench requires its own SQLite backup, release swap and
browser acceptance; neither of these platform service actions deploys it.
