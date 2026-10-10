# Official suite

The official suite owns the business UI composition in `@miy/official-suite-web/modules`, the official API process and its business worker. Shared app contracts own membership and canonical routes; server auth, app admission, resource ACL, AI approval and transactions remain authoritative. This directory provides local implementation candidates. Runtime verification and an authorized release/cutover are separate completion states.

## Current first-party compatibility runtime

| Area | Entry/artifact | Owner boundary |
| --- | --- | --- |
| Platform API | `miy_api.platform_runtime:app` | Common auth/registration/storage/gateway, live realtime transport and existing portal/static update feeds. No official business routes. |
| Official API and UI | `miy_official_api.runtime:app`; `ops/official-suite-api/Dockerfile --target service-runtime` | Official business handlers and the matching `dist/apps/official-suite` UI run in the separate artifact. |
| Platform worker | `miy_worker.first_party_platform:celery_app` | Only `miy.platform.*` queues/tasks. |
| Official worker | `miy_official_worker.runtime:celery_app` | Actual task implementations are in the official worker wheel; only `miy.official.*` queues/tasks. |
| Beat | `miy_worker.first_party_beat:celery_app` | Exactly one scheduler routes the existing periodic jobs to the two owned queue namespaces. |

This trusted first-party runtime reuses the existing database, legacy writer identity, server AuthContext/ACL and existing transactions. It performs no seed, migration, role grant, new Source-only writer or owner-generation takeover. Compatible business-only UI/API/worker updates can replace the official artifacts while the platform image/process remains unchanged; common API/SDK contracts, migrations and shared authority changes retain platform impact. The official API and worker images include matching compatibility wheels built from the reviewed source tree. This is service/release separation, not completed per-service database-credential isolation.

The old `miy_api.platform_main`, `miy_official_api.main` and `miy_official_worker.celery_app` entries remain inactive. Their delegated-auth/Source-only publication candidates and existing verification gates remain available for future work; they are not the current first-party service entrypoints. See the [API owner](api/README.md), [worker owner](worker/README.md), and [first-party topology](../../ops/first-party/README.md).

## UI and navigation

The portal compiles launcher manifests and full-document navigation descriptors, not official business route components. `OfficialSuiteRoot` runs the actual modules using the existing stored login session, common bootstrap, live realtime/shell contexts, notification chrome and personal widgets. The common browser SDK, locale catalog and generic UI primitives are reviewed shared dependencies. Home summaries use a narrow read-client/DTO public entry without loading official view components. The portal build refuses to emit official business view/module/route/sidebar implementations.

Client deep links retain the shared contracts' `/apps/<official-id>` route bases. The official API artifact serves only those client paths and its `/official-suite/` static namespace. Assets use `/official-suite/assets/`; the exact `/recording-sync-sw.js` and `/help/pms/user-guide.html` compatibility URLs retain their existing bytes/scope. Ingress ownership is generated with `python -m miy_api.first_party_routes --nginx-map` and `--client-map`; no second hardcoded per-app HTTP list is required.

The existing default legacy image and rollback path also carry the separate official UI build, paired with that image's portal build ID. Only the legacy API mounts its contract-owned client/static paths before the portal fallback. The first-party platform entry does not serve this compatibility copy; official first-party traffic uses the independent official artifact. The portal still excludes business components in either mode.

The portal's existing dock runs in a fixed same-origin `/official-suite/widgets` document from the official artifact. It reads the existing localStorage session directly and performs its own server-verified bootstrap/API requests. No bearer or permissions are passed by the parent. A generic trusted iframe host observes visible dock/panel/dialog geometry, clips hit areas, and forwards only the existing UI panel-open events. It does not execute official React components in the portal bundle. Personal memo/todo, DM, PMS and Planner panels retain the existing implementation. This embed is for trusted first-party UI; independent user apps keep their separate-origin capability contract.

The reviewed official artifact fixes its platform browser compatibility ID in `.miy-platform-build-id`. Official production startup reads that value once for both the server's existing HTTP/WebSocket build guard and the read-only `/official-suite/platform-build.json` metadata (explicit `null` when the platform has no build ID). Before rendering, official browser startup installs the unchanged HTTP/XHR/WebSocket guard using that same compatibility ID. Neither side discovers or follows the current core ID. Stale API clients receive HTTP 409 or WebSocket 4409. Release checks require equality with the current/candidate platform artifact's `.miy-build-id`; a mismatch fails the existing server guard and release preflight. `MIY_PLATFORM_WEB_BUILD_ID` and the existing Bento URL are Docker build inputs, not runtime authority or app-controlled settings.

## Development and final validation

`pnpm nx dev web` and `pnpm nx dev official-suite` run ports 4200 and 4201 together; the managed root `dev.sh` starts both. Core Vite proxies official client/static paths to 4201 while keeping one browser origin. The official server uses `/official-suite/` for its entry/modules/HMR namespace. Default API routing remains legacy. Explicit `--first-party` uses platform API on the existing port, official API on 18781 through `miy_official_api.development:app`, two owned consumers and one Beat. The launcher generates `.runtime/first-party-api-routes.json` once using `first_party_routes --json`; both Vite configs load that inventory in `first-party` mode. Starting an API-only development target does not require a stale UI build.

After the full requested change stabilizes, consolidate ownership/architecture/type checks, affected API/worker tests, both UI builds and representative authenticated navigation/widget/realtime checks. `pnpm nx build official-suite` outputs `dist/apps/official-suite`; a service image additionally supplies its fixed compatibility file. Do not treat an API health response or source sync as proof of UI, worker, Workbench or production deployment.

Before switching producers, verify the legacy queues and every old consumer's active/reserved/scheduled work are empty, including retries/ETA. Unknown or remaining work stops the cutover. Preserve task IDs and existing data leases/recovery; never purge, silently migrate messages or run two consumers on the same queue. The [worker owner](worker/README.md) records the complete coordinated cutover contract. Root planning/evidence belongs in [platform-redesign](../../platform-redesign/README.md).
