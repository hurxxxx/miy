# Official API composition artifact

`miy_official_api.main:app` is the ASGI entrypoint for the official API wheel. It reuses the existing MIY application factory, router handlers, authentication dependencies, resource ACL and AI contracts. It does not create another identity protocol or copy business handlers. The selected routes are owned by `miy_api.official_api_registry`; the platform-only entry is `miy_api.platform_main:app`. `miy_api.main:app` remains the active legacy composition and preserves all routers in their existing order.

This artifact is **inactive**. HTTP business traffic returns 503 and WebSocket business traffic closes with 1013 before any handler runs. `/healthz` reports only that the artifact can respond, with `activation: inactive`; `/readyz` always returns 503 `service_not_activated`. OpenAPI/docs remain inspectable. No environment flag or request header bypasses this boundary. Constructing either split composition with runtime initialization enabled is rejected. Inactive composition does not initialize PostgreSQL, object storage, AI registries, Hermes sockets or collaboration services, nor mount the legacy frontend/desktop update feed.

From the repository root:

```bash
pnpm nx api-contract official-suite
pnpm nx api-build official-suite
```

The build produces the official entry wheel and its matching MIY API compatibility wheel in `dist/apps/official-suite-api`. Both come from the same checkout; the shared dependency still contains existing platform/business source and the common runtime dependencies remain owned by `apps/api/uv.lock`. The separate [inactive image recipe and offline artifact check](../../../ops/official-suite-api/README.md) package both wheels, existing runtime configuration and the real collaboration codec from stable inputs. It is not added to the production compose/release contract. Source extraction, service authority and writer activation remain separate work.

The [core identity bridge](../../api/src/miy_api/domains/official_apps/README.md) now connects explicitly approved app sessions to the original `AuthContext` for owned official HTTP app scopes. It binds the current verified artifact and installation generation, rechecks admission, preserves source ACLs and avoids login-session last-seen writes. Approval is an internal core operation with no app-facing endpoint. The bridge still reads shared core authority tables; remote introspection, service DB roles and operational WebSocket activation remain pending. The inactive gate above remains in force.

An internal official router assembly can now explicitly supply a separate auth-only
Session factory and its positive read budget. This selects the prepared
[minimal authority reader](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md)
without using the business Source Session for authentication. Default assembly is
unchanged, and reader failure refuses without fallback. Actual Source app admission
and resource ACL still run on the business factory. The published ASGI entry does
not supply these options; its inactive HTTP503/WS1013/readiness503 gates remain.
No role/grant, environment selection, service activation or operational Source
policy is provisioned by this assembly.

The same prepared callable and read budget can now serve the fixed Docs and
Whiteboard collaboration routes. The initial handshake reads delegated authority
before business Source allocation. Existing Yjs receive/send callbacks and idle
monitors recheck that authority and the real Source edit ACL; Docs retains its
writer fence. Reader unavailability closes with private1013 and never switches to
platform-token auth. Existing default collaboration helpers and the published
inactive WS1013 gate remain unchanged. The focused native proof uses an isolated
legacy business Source role and synthetic rooms/bus, so complete Source/hub roles,
relay/persistence operations and deployed activation remain required. The reader
owner above records this boundary and cancellation limits.

An explicit prepared assembly can additionally select a separate Whiteboard
ACL-read Session factory and positive Source budget. The ACL callback loads only
board authority fields, reuses current app/group/admin/target policy, then repeats
the same prepared auth check after Source cleanup. It shares the accepted
structured worker API, with a distinct Source limiter. No environment or request
selects it, and failure never selects the global factory as recovery. Initial
room creation, scene/Yjs state and hub persistence still use the original business
Source lifecycle. The [reader owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#explicit-inactive-whiteboard-acl-reads)
distinguishes the disposable ACL-read fixture from a complete operational Source
privilege profile; the published inactive artifact still supplies no such options.

An additional explicit room-read factory and budget can select an existing
Whiteboard collab row for the initial handshake. This prepared branch enforces a
coherent 8 MiB aggregate scene/snapshot/Yjs bound, refuses missing or stale state
without initialization or repair, and repeats the same current auth identity after
Source cleanup. Complete server assembly is checked before room or slot admission;
failure never falls back to the global initial factory. The
[initial-room reader owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#explicit-inactive-whiteboard-initial-room-reads)
records separate budgets, restricted fixture scope and current-observation limits.
Default initialization and the native global persistence factory remain selected;
this option does not provision a Source writer, roles or service activation.

The trusted Whiteboard runtime now retains the admitted collab row ID and room key
and conditionally saves only that same live incarnation. Rotation or same-key row
recreation cannot make an old flush adopt a replacement. Each hub admits at most
four persistence workers across its rooms and holds each permit through owned
cleanup and joined outcome transfer; canceled ordinary admission waits allocate
no Session. Final disposal retains pending bytes before admission and joins its
shielded owner through final work and native cleanup. Accepted cleanup waits and
the whole shutdown lifecycle likewise join their owners before caller cancellation
returns. Its admission wait is separate
from the admitted SQL budget and other cleanup time limits, so timeout cannot discard
an unsaved waiting room. This is a per-hub bound with no new operational setting.
Its SQL worker stays
joined under cancellation until owned cleanup, with decreasing local SQL budgets;
ACK is preserved before close, and unknown/refused attempts retire without automatic
replay. A local unknown-incarnation tombstone blocks re-admission from a same-row
Source observation until separate resolution; it is not durable restart history.
The same incarnation also refuses admission while a removed runtime still has
pending SQL/disposal; only complete joined disposal clears that temporary marker.
The native finalizer and local callbacks preserve replacement runtime
identity. ID-less memory-only room construction grants no persistence authority.
The [runtime persistence owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#trusted-whiteboard-runtime-persistence-safety)
distinguishes this existing global-factory safety change from a separately accepted
Source writer/profile, current Core authority through COMMIT, cross-hub content CAS,
relay incarnation and durable historical ACK recovery. Docs persistence and all
inactive service gates retain their original contracts.

An explicit prepared assembly can also pair a separate Docs ACL-read factory
with a separate Core writer-read factory and their positive budgets. The Docs
callback reads page/doc authority fields and current ACL without content/display
graphs; the Core callback reuses the original pinned writer check before and after
Source cleanup. The same captured auth callable rechecks the original actor and
source-session identity, and changed callback/hub/writer bindings refuse privately.
SQL/catalog reader failures remain distinct from actual native writer fencing.
The small public owned-read Session guard is shared with Whiteboard while its
private refusal wrappers and policy8/20 alias remain compatible. Auth14/87 and
existing SQL role/profile contracts are unchanged. The
[reader owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#explicit-inactive-docs-acl-and-core-writer-reads)
records the independent budgets, disposable role proof and limits. Initial Docs
room initialization, COMMIT, hub relay writer reads, persistence/media/RAG remain
on the native business lifecycle. This is an inactive frame/monitor seam; it
provisions no roles or service settings and does not complete a Source-only runtime.

A complete prepared Docs assembly can further select a separate existing-room
Source factory and read budget. The initial read uses the current18-model closure,
a coherent page/doc/collab projection and combined8MiB JSON/Yjs bound, with current
ACL, pinned Core writer and same actor/source-session checks before native room
admission. SQL NULL/JSON null and None/empty Yjs remain distinct; states requiring
native initialization/repair refuse privately. The exact canonical key and page
creator are preserved without a new timestamp/equality rule. Configured failure
never falls back to global initial Source allocation. The
[reader owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#explicit-inactive-docs-existing-room-source-reads)
records the bounded native proof, independent budgets and limits. Default initial
writes, HTTP creation/snapshots, hub persistence/relay writer reads and media/RAG
retain their native lifecycle. This inactive read seam does not install roles,
activate a split service or complete Source-only persistence.

An additive inactive Whiteboard Source service-admission profile now owns only
column SELECT on two tables (8 columns), column UPDATE on 4 columns and one private
authority capability. Core preparation accepts fresh supplied roles or exact
complete mutation-free replay; broad, partial, revoked and altered bindings refuse.
The frozen original writer and catalog owner identities are compared with actual
direct `session_user`; the fixed SQL capability keeps service ownership/principal
SHARE locks through the caller's COMMIT or rollback. It creates no credentials or
roles, owns no transaction/worker lifecycle, and selects no Source factory. The
[service writer owner](../../api/src/miy_api/domains/official_apps/AUTHORITY_READER.md#inactive-whiteboard-source-service-writer-admission)
records migration-versus-hardened-admission rules, effective privilege limits and
private refusal. User/resource ACL, current Core authority through COMMIT, detached
write bounds and Source factory activation remain separate required steps. This
service-only fence supplies no user authorization or saved ACK; current runtime
persistence and inactive service gates retain their contracts.

| Artifact                  | Current state                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------------- |
| Official UI               | Separate entry/build output; legacy UI/public-module bridge                                          |
| Official API              | Separate wheel/ASGI entry and owned route/schema set; activation closed                              |
| Platform API              | Separate ASGI entry within the existing API wheel; activation closed                                 |
| Legacy API                | Existing active composition, runtime initialization and single writer                                |
| Worker / Beat             | Active legacy worker; separate inactive platform/official profiles and owned queues, no new consumer |
| Service image             | Local inactive image recipe and offline check; no production release contract                        |
| Routing / database writer | No activation or production cutover                                                                  |

The [worker owner](../../worker/README.md) records the inactive profiles, matching wheel evidence and remaining claim/lease/outbox activation requirements.

The [cutover owner](../../../platform-redesign/OFFICIAL_API_CUTOVER.md) records the concrete shared writes, fencing, identity delegation, router generation, database roles and worker/outbox steps required before activation. Publishing a health endpoint or building a wheel does not satisfy those steps.
