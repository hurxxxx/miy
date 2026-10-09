# Prepared official authority reader

`authority_reader.resolve_prepared_official_auth_context` is an inactive,
core-owned lookup seam. It accepts an opaque app-session credential and trusted
canonical logical app scope, then reuses current official binding, release
verification, independent-app identity and company/app admission rules. No app
manifest, settings default or deployed service selects this reader. A trusted
server-only HTTP/Docs/Whiteboard WebSocket assembly can explicitly select it using a separate auth factory;
platform login and the default official HTTP adapter remain unchanged.

## Explicit inactive HTTP assembly

`register_api_routers` accepts paired `official_auth_session_factory` and
`official_auth_max_concurrent_reads` options only for the official composition.
With neither, the existing HTTP adapter remains selected. Partial configuration,
another composition, a non-callable factory or a non-positive/non-integer budget
refuses assembly. No request, app manifest or environment flag chooses these options.

The prepared dependency validates owned canonical scope and bearer credentials
before allocating the auth Session. It invokes the unchanged reader in an AnyIO
worker with a private limiter sized by the auth Engine owner, separate from the
business Source factory and pool. The limiter is created in the ASGI async context;
its budget bounds executing reads, not HTTP waiters or other service workers.
An outer read permit surrounds a public AnyIO TaskGroup; its private child shields
the thread await and uses a per-call worker limiter. The group joins reader and
cleanup before releasing admission under supported AnyIO scope cancellation and
raw/repeated host request-task cancellation. A canceled admission waiter creates
no Session. Original child exceptions are raised outside the group, without
changing policy or cancellation into an ExceptionGroup. The child is not exposed
for direct cancellation. Hard process kill, event-loop shutdown and an uncooperative
driver/cleanup hard deadline are not guaranteed by this composition.
Existing SQL timeouts are not a whole-request deadline. Reader control or SQLAlchemy
failures return a fixed localized503 without private details or a broad-reader
fallback; current credential/admission401/403 and cancellation remain distinct.

The returned detached context is cached only by the existing request dependency
chain. Current app policy and resource ACL are still enforced by the real Source
handler. A successful lookup does not freeze permission through later waits or
writes. This assembly does not install an operational auth role, activate the split
ASGI artifact or complete the business Source privilege policy. Removing the options
restores default assembly; runtime failure never selects that default as recovery.

## Explicit inactive collaboration assembly

The same registry-built callable accepts public Starlette `HTTPConnection` and is
retained only in server-owned application state. Prepared Docs and Whiteboard
WebSockets reuse that exact callable and its read limiter; they do not construct a
Request, another reader or a second pool budget. The route owns the fixed `docs`
or `whiteboard` scope. Caller headers, query scope and auth-frame extra fields do
not choose authority. Query credentials remain refused by the existing handshake.
The small `websocket_auth.py` adapter belongs to this domain; business routers do
not import an API composition root.

Prepared lookup finishes before initial business Source allocation. The unchanged
Source page/board loaders still enforce current app admission and edit ACL. Docs
also retains its current writer identity, initial transaction fence and frame
writer check. A read share cannot open an edit room. Every Yjs receive, outgoing
send and idle monitor performs a fresh prepared lookup before Source ACL access;
a connected socket and an earlier detached context are not continuing grants.
The initial actor must remain the same on subsequent checks. The existing public
Yjs authorization callbacks, room slots, hub cleanup and persistence remain owned
by their original modules.

Credential/policy denial preserves existing handshake4401/4403/4404 and per-frame
access revocation1008. Reader control/SQLAlchemy failure chooses private1013
`official_authority_unavailable` without Source allocation, platform-auth fallback
or fencing another client's room. Docs writer failure retains its separate1013
writer fence. Cancellation remains cancellation and uses the accepted structured
reader cleanup contract. Removing prepared state during a connection refuses its
next prepared check; it does not adopt the legacy reader. Default construction
keeps the original platform-token collaboration helpers.

`tests/test_prepared_official_ws_auth.py` exercises real migrated PostgreSQL and the
exact14/87 auth role, delegated/source/binding/app/user revocation, actual Source
edit denial and Docs writer drain. Its business Source factory is the isolated
legacy fixture, not an operational minimal Source role. Its room/bus are synthetic
and invoke the unchanged Yjs transport callbacks; no live relay, codec, room
persistence, service deployment or operational authority is accepted by that proof.

## Explicit inactive Whiteboard ACL reads

An official assembly that already supplies prepared auth can also explicitly
supply `official_whiteboard_source_session_factory` and
`official_whiteboard_source_max_concurrent_reads`. Both are required together.
The captured callback has a separate positive Source read budget. HTTP auth and
Source reads reuse the public domain `owned_read.run_owned_read` structured worker;
the auth limiter and its existing cancellation and failure behavior remain unchanged.
Default assembly supplies neither Source option and retains its original callback.

The Source callback refuses borrowed, cached, pending, connection-bound or routed
Sessions before SQL or cleanup ownership. A factory must use standard public
`Session.get_bind`, one Engine for the fixed current ACL model set, PostgreSQL
READ COMMITTED and non-autocommit. Owned reads use a read-only transaction,
canonical local search path and the existing five/fifteen-second SQL limits.
Owned rollback/close attempts finish before the callback returns; a failure
attempts invalidation and cannot replace the original policy or cancellation outcome.
SQL/control failures return the same private localized503, without a default
Source factory fallback. Policy403/404 and cancellation retain their types.

`collab_source_access.CORE_POLICY_READ_COLUMNS` records eight existing Core policy
tables and twenty safe columns, a subset of the existing Source policy contract.
Current app, user, admin, local/HR group and registered target predicates are
reused. The ACL-only board loader selects five fields with deferred-column and
relationship raise guards; it does not load the scene, title, owner or share-user
graphs. Existing PMS/Meeting target adapters still load their original Source
models. No predicate is replaced by a detached auth context.

The callback reuses the existing private `writer_roles._role` catalog check for
direct nonprivileged LOGIN attributes, membership, ownership and parameter grants.
This reuse is not a full privilege-manifest attestation or a new role preparation
API; the helper's existing namespace-prefix checking limits remain. Focused tests
use a disposable ACL-read login with column-only Core/board reads and SELECT on
nine existing Source target/share tables. They do not establish an operational
minimal Source or hub role, and product code creates no roles or grants.

After Source read cleanup, the route calls the same prepared auth dependency
again and requires the original actor and source-session identity before continuing.
Current source-session or app denial across a Source wait therefore refuses the
frame. This is a current admission check, not an atomic freeze of ACL until a
later write. Original room initialization, scene/Yjs state and global business
factory selection continue; trusted Whiteboard persistence safety is recorded
below. Source-only lifecycle ownership, the full Source privilege profile and
operational activation remain cutover work.
`tests/test_prepared_whiteboard_source_access.py` owns the bounded ACL-role,
namespace, ownership, wait/revocation and cancellation checks. Its room/bus and
initialization factory remain isolated synthetic business fixtures.

## Explicit inactive Whiteboard initial room reads

The same explicit assembly can additionally supply
`official_whiteboard_room_session_factory` and
`official_whiteboard_room_max_concurrent_reads`, together with the prepared auth
and ACL options. A server-owned configured marker records this complete assembly;
it grants no authority. Missing or noncallable dependencies refuse with private
503/1013 before global initial Session, room or connection-slot allocation. Auth,
ACL and initial room reads have separate budgets, not a combined concurrency cap.

`collab_source_room` reads only an existing board/collab pair. One SQL projection
measures the sum of the scene and snapshot JSON UTF-8 text representation and raw
Yjs bytes against a fixed 8 MiB bound; CASE expressions withhold all three bodies
when oversized. The transferred DTO is checked again before use. Null Yjs remains
valid, and the existing empty-scene behavior and current room key are preserved.
Missing, stale, mismatched, invalid or oversized state refuses instead of creating,
repairing, resetting, flushing, committing or selecting a global factory fallback.
The reader checks current app/edit policy before the body and again after clearing
its owned ORM identity snapshot. The paired read is a current observation, not a
lock on room state for a later write.

After Source cleanup, the route reuses the identical prepared auth callable and
requires the original actor and source-session identity. The configured marker,
auth dependency, room loader and ACL callback identities are checked before and
after this final await. Revocation across a Source wait refuses before room or
connection-slot admission. Reads reuse the same owned transaction guard and
structured worker; supported request cancellation joins cleanup before releasing
that reader's permit, without a hard process-kill or event-loop-shutdown guarantee.

The isolated native fixture extends the existing ACL-read fixture only with two
board columns and six collab columns. Its eight Core policy tables/twenty columns
and nine existing Source target/share table reads retain the ACL owner's limits.
This is not exact operational Source-profile attestation; the private catalog-role
check has the same documented limitation. Synthetic room/bus fixtures establish
route ordering and callbacks, not deployed codec, relay or persistence operation.
Default initialization, scene/Yjs behavior and the native hub's global persistence
factory remain selected. The trusted runtime safety contract below adds captured
incarnation checks and joined persistence without turning this reader into a writer.
Separate Source authority, complete roles and operational activation remain pending.

## Inactive Whiteboard Source service writer admission

`whiteboard_source_writer_roles` owns the immutable
`whiteboard_source_service_admission_v1` profile. It supplies no runtime factory
or default service selection. Core may explicitly prepare fresh supplied roles
in its existing admin/CAS transaction; product startup creates no roles,
credentials, operational grants or activation.

The Source LOGIN has column SELECT only on `whiteboards(id, trashed_at)` and
`whiteboard_collab_documents(id, whiteboard_id, room_key, yjs_state, updated_at,
writer_scope)`, column UPDATE only on `whiteboards(writer_scope)` and
`whiteboard_collab_documents(yjs_state, updated_at, writer_scope)`, and one private
authority EXEC, `public.miy_whiteboard_lock_source_writer(integer,text)`.
Board `writer_scope` UPDATE enables the existing SELECT FOR SHARE; collab
`writer_scope` SELECT/UPDATE enables the protected zero-row source trigger.
This grants no board owner, target/share/group/PMS/meeting ACL or Core/auth reads.
Table-wide grants, initialization/INSERT/DELETE, snapshot/key rewrite, other app
data, membership, CREATE, ownership, sequences and grant options are forbidden.
All current-database user namespaces use a literal `pg_` prefix exclusion; PUBLIC
and effective column privileges are included. Harmless ordinary invoker function
EXEC is not claimed absent: arbitrary executable SECURITY DEFINER, owned and
grantable functions are refused, and the generic producer locker is never directly
executable by this Source LOGIN.

The fixed additive migration installs the inactive capability under the original
Core migration owner, checks the exact canonical 88-source/2-transport inventory
in either legacy or hardened mode, and revokes PUBLIC EXEC in the same transaction.
It changes no existing function, role guard or role grants. Preparation and runtime
admission additionally require the exact hardened source guard and immutable
principal trigger. Fixed signatures, unique public-name overload inventories,
UTF-8 body hashes, language/result/defaults, security/configuration and explicitly
supplied original owner OIDs are checked for the new capability, producer locker,
source guard and principal guard. An unexpected existing function is refused;
there is no CREATE OR REPLACE or catalog repair.

`install_whiteboard_source_writer_guard` runs only during an explicit Core draining
CAS. Its supplied NOLOGIN owner must be fresh and restricted; the original expected
migration owner OID is mandatory before ownership transfer. This owner has only
the new capability ownership, public USAGE and existing producer locker EXEC.
Temporary schema CREATE used for transfer is revoked in the same transaction.
Exact complete owner replay performs no grants, ALTER or audit. Partial, altered
or unexpectedly owned capabilities are not repaired. Principal preparation binds
the supplied direct LOGIN once to original `official.suite/legacy`, generation
and non-null SHA-256 artifact. Existing broad/read/Files, partial, revoked or
different OID/name/identity bindings refuse. Exact complete replay validates the
current catalog and immutable identity with mutation zero; there is no historical
profile-version ledger or silent future profile expansion.

The frozen server descriptor retains that original WriterIdentity, Source OID/name
and original capability/producer/source-guard owner OIDs. In
`admit_whiteboard_source_writer`, actual direct `session_user` OID/name must match
the descriptor. The SQL capability independently obtains the safe LOGIN OID/name
from actual `session_user`; its only arguments are original expected generation
and artifact. Scope/owner remain fixed. SET ROLE, GUC values, detached users and
room payloads do not provide identity, and current DB generation/artifact is never
adopted. The existing producer primitive locks RuntimeOwnership followed by the
immutable RuntimePrincipal FOR SHARE, re-evaluates after waits and holds locks
through the caller's real COMMIT/rollback.

Admission owns no Session, factory, save, COMMIT, rollback or close. It requires
READ COMMITTED/non-autocommit, sets only a transaction-local canonical namespace,
and preserves the caller's decreasing SQL budget and cleanup ownership. Private
failure does not expose SQL or credentials. Catalog checks are admission-time
checks; they do not freeze independent superuser DDL/grants. A successful service
fence is neither current actor/resource ACL authority nor a persistence ACK.

The current paired room reader's combined 8MiB JSON/Yjs limit is unchanged.
This body-free capability implements no new Source-write payload limit or worker.
Future factory wiring must first accept current Writer ACL closure and the
separate current Core actor authority-through-COMMIT contract, detached write
bounds, and reuse the existing per-hub cap4/flush-lock/private joined SQL worker,
ACK/unknown/no-replay lifecycle below. Same-incarnation content revision/convergence,
durable unknown/ACK restart history and Docs media/materialization remain later
work. Hub, registry, trusted business factory and inactive HTTP/WS gates are
unchanged. `tests/test_whiteboard_source_writer.py` owns isolated restricted-LOGIN
SQL proof; its synthetic CAS authority does not prove a real user's resource ACL.

## Trusted Whiteboard runtime persistence safety

Both native initialization and the prepared paired reader preserve the already
loaded collab row ID in `WhiteboardCollabContext.collab_document_id`. This is an
opaque nonempty bounded String(36), including existing non-UUID IDs. The hub keeps
the original board ID, collab row ID and room key as a frozen persistence identity;
it does not discover or adopt a new row at flush time. Same-key incoming incarnation
changes retire the old native runtime instead of returning its YDoc. Local YDoc,
message, relay and queued publish callbacks check the exact current runtime, so a
late old callback cannot schedule or publish through its replacement's key.
Only the exact native empty transaction delta `b"\x00\x00"` is ignored before
hashing, scheduling or publishing; delete-only and other real updates are retained.
The relay wire format is unchanged; already accepted external publications and
cross-process same-key incarnation isolation are separate work.

The runtime always calls `scene_state.persist_runtime_yjs_state` with paired
`expected_collab_id` and `expected_room_key`. It requires a fresh factory-owned
Session on one PostgreSQL Engine, READ COMMITTED and non-autocommit. The local
guard accepts the existing Session subclass instrumentation; it does not apply the
prepared read-only role profile or install a new writer grant. Rejected borrowed,
cached or pending caller work receives no rollback/close ownership. An owned
transaction sets `pg_catalog, public, pg_temp` locally and locks the live board
before an exact conditional collab UPDATE/RETURNING on board ID, captured row ID
and key. Zero rows refuse. Runtime persistence never initializes, inserts, repairs,
rotates a key or replaces a snapshot. Equal Yjs preserves the existing timestamp;
native REST initialization/snapshot commands keep their existing contracts.

The helper's deliberately trusted neither-expected-argument call form retains its
original current-room lookup/initialization and `None` return. Supplying only one
expected value is invalid. ID-less direct in-memory hub construction still permits
slot tests, but its flush refuses before factory allocation; missing capture never
selects that trusted compatibility branch. This is an internal distinction, not a
new public app API or a Source writer activation switch.

Each hub shares a fixed four-permit persistence limiter across all its rooms.
The parent holds the room flush lock and acquires that shared permit before
starting the private shielded AnyIO child. Ordinary flush shared-permit waits
remain cancellable and allocate no Session. After the wait, terminal/disposing state, the original
captured identity, native YDoc, uncertain incarnation and current hub runtime are
checked again; the private disposing final flush keeps its existing allowance.
The native encode/validation before child startup has no await. Ordinary flush
cancellation while waiting for the shared permit allocates no Session; once the
private child starts, parent cancellation joins it through owned cleanup and
outcome transfer.
The shared permit stays held through the actual SQL worker, complete owned cleanup,
child outcome transfer and task-group join. Its internal one-worker thread limiter
is the accepted owned-worker adapter, not another room admission budget; the outer
shared four-permit limiter bounds active persistence workers across this hub.
This bound is per hub, not process-wide, and adds no operational setting.
Raw or repeated host cancellation joins the child before releasing the shared
permit and room flush lock; a canceled lock waiter also allocates no Session.
Only detached bytes cross to SQL. A decreasing
per-Connection PostgreSQL statement/lock budget covers application SQL and is
refreshed immediately before COMMIT. Transaction-local settings reset with the
transaction. Pool acquisition, driver connection/cleanup, network failure, process
kill and event-loop shutdown are not given a hard-stop guarantee.

The worker records `acknowledged` immediately when `Session.commit()` returns,
before best-effort close/invalidation. The private child transfers that outcome
to the owning runtime before forwarding parent cancellation. Cleanup failure never
demotes a known ACK. A COMMIT exception defaults to `unknown`; only the shared
narrow explicit PostgreSQL rejection classifier plus successful rollback establishes
`rejected`. Failed rollback remains unknown. Missing/stale identity gives `refused`.
Only fixed private control reasons leave this worker, not SQL errors or body bytes.

Unknown/refused/rejected runtimes become terminal, retaining original identity and
their detached payload internally while retiring only their own room. Debounce,
cleanup, disposal and shutdown never replay that terminal attempt.
An unknown attempt also leaves a local incarnation tombstone after native room
disposal. A fresh observation of the same board/row/key cannot clear uncertainty or
admit another runtime for it; the hub preserves the original attempt internally.
Removing a runtime from the map first marks its captured incarnation as retiring.
Same-incarnation admission refuses while its SQL worker and native disposal remain
pending. The marker clears only after complete joined disposal; an unknown result
continues to refuse through its separate tombstone. If a same-incarnation runtime
was already present when uncertainty was registered, it is terminally closed rather
than left as an open connection whose frames are silently skipped.
A different admitted incarnation can be reconstructed without adopting old bytes.
This in-memory control has no claim to process-restart history or automatic recovery.
Normal automatic final cleanup also skips bytes already acknowledged; a deliberate new current-room
flush still verifies its captured row in a fresh transaction and can acknowledge an
equal-byte timestamp no-op. Later distinct native edits remain possible after ACK.
The production finalizer supplies `expected_runtime`; an old connection cannot
remove, persist or release a same-key replacement. Disposal joins its own tasks and
releases native YRoom state on the owning event loop.

Final disposal has a private shielded lifecycle owner joined by its parent.
An accepted `cleanup_room` disposal wait also has a private shielded joined owner;
its caller cannot return on cancellation while that disposal still runs. The whole
shutdown lifecycle runs in another private shielded joined owner, including room
detachment, all disposal waits and bus shutdown. Caller cancellation cannot cancel
the disposal gather and return after only its first completed child. Errors remain
propagated rather than being converted to successful cleanup.
Under the room flush lock final disposal first joins earlier work, compares the current native bytes
to the last ACK and retains any final pending bytes before admission. Final flush
then awaits the shared permit directly, without the non-SQL cleanup timeout
wrapping that wait. The SQL statement/lock budget starts in the admitted worker's
Session, while client/relay/room cleanup steps keep their separate time limits.
Repeated cleanup/shutdown parent cancellation joins final admission, worker
cleanup, outcome transfer and native disposal before being forwarded. Native YDoc
and its captured identity stay owned until that final work completes; only a known
ACK clears retained bytes. Refusal/unknown preserves the detached buffer and its
existing terminal controls without automatic replay. There is no hard overall
shutdown/admission, driver, network, process-kill or event-loop guarantee.

This first step uses the existing trusted global business factory and statement
writer fence. It does not provision minimal Source privileges or a new principal,
hold current Core user authority through Source COMMIT, prove same-incarnation
cross-hub content convergence, or keep durable historical ACK/restart receipts.
An independent later observation is current stored state, not historical ACK and
not replay permission. Docs materialization/media/projection persistence and the
published split-service inactive gates are unchanged. The new focused persistence
tests own actual isolated PostgreSQL/native Yjs proof; structural validation and
release/service activation remain separately reported gates.

## Explicit inactive Docs ACL and Core writer reads

An official assembly with prepared auth can explicitly pair
`official_docs_source_session_factory` / `official_docs_source_max_concurrent_reads`
with `official_writer_read_session_factory` / `official_writer_read_max_concurrent_reads`.
Complete callable factories and positive integer budgets are checked before state
or dependency mutation. Construction allocates no SQL Session or room. The server
records `prepared_docs_source_configured`; this sentinel is neither user authority
nor a split-service activation switch. Default assembly supplies none of these
options and keeps the original prepared/default collaboration helpers.

The Docs Source callback loads only native page ID/doc ID/content format/trash and
doc ID/owner/ownership kind/company visibility/trash, with deferred-column and
relationship raise guards. It preserves the native-page-only, block-format edit
scope and current app/direct/local-HR-group/MeetingAccess/PMS-target predicates.
It does not load page content, owner/created-by/share-user/collection graphs or link
credentials. Its fixed routing closure is17 models: Core policy8, Docs6 and PMS3.
The current Docs target adapter has PMS spaces; this is not a universal privilege
closure for future registered adapters.

`owned_read_session.py` owns the small fresh/single-Engine, read-only transaction
and non-replacing cleanup guards shared with Whiteboard. Existing Whiteboard
`_fresh`, `_cleanup`, transaction wrapper and private refusal class/reasons remain
compatible; its ACL18 and room19 model closures stay distinct. The exact existing
Core policy8-table/20-column dictionary moves to this public owner and remains
re-exported as Whiteboard's `CORE_POLICY_READ_COLUMNS`. It does not adopt the wider
F2 policy9-table/27-column manifest or change any existing role/profile/SQL contract.
The auth14/87 reader is unchanged and does not use this extraction.

The separate Core callback reads only current `RuntimeOwnership` using the
unchanged `require_active_writer` and the hub's original pinned `WriterIdentity`.
It never discovers/adopts a generation, binds a Source write transaction or reads
Source content. Current Core writer admission runs before and after the Source ACL
read. Auth runs before and after the whole joined read sequence; after each await,
exact captured auth/Source/Core callables, hub and writer-identity object, actor and
original source-session identity must still match. Removing/rebinding assembly
refuses privately rather than using the global factory. These repeated reads are
not an atomic permission freeze through later Yjs execution or a SQL commit fence.

Each callback uses the unchanged `owned_read.run_owned_read` joined worker API and
an independent limiter. Auth, Source and Core budgets are separate; neither their
sum nor per-statement SQL timeouts is a whole-process/request deadline. Rejected
borrowed/routed/cached/pending Sessions get no SQL or cleanup ownership. Queued or
running/repeated cancellation preserves the existing worker/permit ownership
contract. Cleanup attempts cannot replace policy or cancellation outcomes.
Reader/session/catalog/SQL failures use authority-unavailable503/private1013 and
do not fence another client's room. Only the existing exact localized writer
unavailability keeps native writer1013 and room fencing; policy401/403/404 stays
distinct. Credentials and internal refusal reasons never appear in responses.

`test_prepared_docs_source_access.py` defines disposable migrated Source and Core
read fixtures, native transport receive/send/idle-monitor effects with a synthetic
room/bus, exact captured-identity refusal and SQL lock-wait/cancellation boundaries.
The Source fixture has column-only Core policy/doc/page reads and SELECT on seven
existing share/target/PMS tables; the Core fixture reads the six mapped ownership
columns. These bounded fixtures are not operational privilege-manifest attestation,
a live relay/codec/store proof or deployed activation.

Without the optional existing-room read assembly below, initial Docs room
loading/creation/Yjs initialization and COMMIT still use the original business
Source transaction. Hub relay writer reads and persistence keep their native
business lifecycle in either composition. The initial ACL assembly guard alone
does not reroute those writes to a readonly factory. Docs media writes, RAG/outbox and actor policy remain structural cutover
work. This slice is an inactive frame/monitor read seam, not a complete Source-only
Docs process. The published artifact still supplies no prepared options and retains
its inactive HTTP503/WS1013/readiness503 boundary. Product code provisions no roles,
grants, credentials, environment settings or service activation.

## Explicit inactive Docs existing-room Source reads

A complete prepared auth/Docs ACL/Core writer assembly can additionally supply
`official_docs_room_source_session_factory` and
`official_docs_room_source_max_concurrent_reads`. Both are server-only and must
be supplied together with a callable factory and positive integer budget before
state/dependency mutation. The new `prepared_docs_room_configured` sentinel and
captured `prepared_docs_room_loader` select only an existing-state read; no env,
client data or sentinel is user authority or service activation. Absent options
retain the original initial room transaction. Partial/missing/rebound configured
state fails privately and never uses that global initial factory as recovery.

The loader uses the unchanged public owned-read Session guards and structured
worker, adding only `DocsCollabDocument` to the fixed Docs17 routing closure.
Its separate positive limiter does not make the auth/ACL/Core/room budgets one
process/request deadline. Current app and native page/parent edit ACL run before
and after a coherent Page/Doc/Collab projection; the final read discards the first
ORM identity snapshot and checks the parent binding. Content and creator metadata
are detached Source data, never actor/session/writer authority.

One paired SQL CASE computes the combined UTF-8 page/snapshot JSON and raw Yjs
length, refusing bodies above8MiB before driver/Python transfer. The detached DTO
rechecks exact transferred bytes and normalized size. SQL NULL contributes zero
wire bytes, while JSON text `null` contributes four; both decode to native None.
Deferred content text/title/user/display/collection graphs and writer scope are
not loaded. The default scene/editor/codec settings and Source SQL schema are not
changed by this prepared-only bound.

Native semantics are retained: only native_doc_page references, canonical exact
`native_doc_page:{normalizedId}` key, and page.created_by_id as default actor.
There is no timestamp stale check, key suffix/rotation or page/snapshot equality
rule. A missing collab row, changed source/parent/key, or state needing native
snapshot/Yjs initialization is private not-ready503/1013 rather than create,
repair, seed, codec or COMMIT. Yjs None plus non-None page blocks needs repair,
including []; b'' is kept distinct. Meaningful page/snapshot bodies with absent
or empty Yjs refuse to prevent empty-room content loss. Legitimate empty
page/snapshot None with null or empty bytes retains native empty-YDoc semantics.
The loader performs no Y.py or Node codec operation in the SQL worker.

The initial route checks the same captured auth/ACL/Core/room callables, hub and
pinned writer object before and after awaits. Core writer admission surrounds
room read/cleanup; the same auth callable then rechecks the original actor and
source-session before native room/slot admission. Removal or rebinding refuses;
no current generation or client writer identity is adopted. Frame/monitor
continuation retains the accepted ACL/Core/auth helper and additionally refuses
changed room assembly. These current reads do not freeze authority through later
Yjs execution or replace a Source commit fence. Reader-control/SQL failure remains
private authority-unavailable without fencing another client's room; actual
writer unavailability keeps the existing native fence behavior.

`test_prepared_docs_source_room.py` defines migrated bounded Source18 reads,
actual BlockNote codec/Y.py/YRoom positives with a qualified in-process bus,
SQLNULL/JSONnull and null/empty state cases, coherent aggregate bounds,
repair/no-admission failures, retained current ACL/auth, cancellation/cleanup and
rebind tests. Its transport rooms are qualified synthetic fixtures and its
room-read fixture explicitly adds only two page and six collab columns to the
accepted ACL fixture. It is not an operational role/grant ceiling or deployed
complete Source-only Docs service. Product code installs no roles, credentials,
service configuration or activation.

HTTP room creation/snapshots, hub relay writer reads, persistence/media/RAG and
Source writer/current actor/commit-outcome policy remain structural cutover work.
The published inactive HTTP503/WS1013/readiness503 boundary is unchanged.

## Ownership and current authority

The caller supplies a factory for a fresh **auth-only** SQLAlchemy Session,
separate from the business Source Session. Before SQL or cleanup ownership,
the reader requires standard public `Session.get_bind`, one Engine for every
authority mapper/table, an empty identity map and no active transaction or
pending work. Custom routing, connection binds, cached or active caller sessions
are refused without clearing objects or rolling back their work.

The owned Session requires PostgreSQL, actual READ COMMITTED and non-autocommit.
The first isolation read is `SHOW transaction_isolation`, so a caller search path
cannot replace a same-signature function. Its transaction is read-only, with
`pg_catalog, public, pg_temp` and local 5-second lock/15-second statement limits.
Persistent authority is read from public even when a pooled connection has
temporary shadow tables.

The existing lifecycle receives a typed, server-only optional source-user loader.
Explicit `None` keeps the current full-graph reader. The prepared path loads
User id/status/password-change policy/primary organisation/display name/full
name/email/locale/time zone and selected AuthSession id/user id/expiry/revocation/
impersonation fields. It does not load password hashes, source credential hashes,
other login sessions or organisation relationships. These original models form
the same `AuthContext`; no second authentication or identity protocol is introduced.
Final app admission is rechecked; a system-role change during that check refuses
the lookup instead of returning the earlier roles. There is no implicit retry.

Success returns detached models with only safe scalars loaded. Deferred credential
columns and relationships cannot issue later SQL. Lookup does not update
last-seen, write audit or commit. Rollback/close failures cannot mask denial or
cancellation; cleanup failure attempts invalidation, and the owned Session is
never reused. Delegated credential revocation/expiry is read again before detaching;
both delegated and source-session expiry are checked after cleanup. A lookup
result is not durable authority: business resource ACL and write/approval actions
must still check current authority in their own transaction. Revocation after
return is not frozen by this reader.

## Restricted login profile

`AUTHORITY_READ_COLUMNS` in the module owns the exact 14-table column manifest,
including all columns currently read by reused installation/release/binding/
verification ORM queries. Only the app-session hash used for lookup is included;
the source login hash is excluded. Do not widen this profile to run a full user
graph or business handler.

The actual login must be direct, NOINHERIT, nonprivileged, without role membership,
persistent object ownership or privileged parameter grants. Existing owned
principal/sequence checks are reused. Current-database non-system schemas are
checked for unexpected reads, table/column DML, grant options, schema CREATE,
sequence privileges and executable SECURITY DEFINER/owned/grantable functions.
All required reads must be present with no other application-table reads. TEMP is
permitted; temporary tables do not replace canonical reads. This is not an
inventory of other databases or host privileges.

The reader additionally checks literal `pg_` namespace prefixes and relations
without user columns. The existing principal helpers use a broader SQL LIKE
pattern and do not own this exact read manifest; those helpers remain unchanged.

The product does **not** create, grant or configure operational roles. Tests
provision fresh roles in an owned disposable migrated database. Actual role
preparation, credential distribution and a matched independent service artifact
require separate approved delivery work. This auth-only profile cannot be
assigned as the business Source writer profile.

## Remaining cutover

Operational HTTP/WS activation and complete Source/hub privilege profiles, non-launcher identity scopes, source-access/search/AI approval/
audit consumers, independent service credentials, queue ownership and old-writer
drain remain required in the [cutover plan](../../../../../../platform-redesign/OFFICIAL_API_CUTOVER.md).
This seam does not activate the suite or remove the inactive composition gate.
`tests/test_official_authority_reader.py` owns focused profile/current policy/
namespace/session-ownership cases; evidence belongs to `platform-redesign/VALIDATION.md`.
`tests/test_prepared_official_http_auth.py` owns explicit HTTP assembly, separate
restricted auth-role admission, real current Source ACL and cancellation boundaries.
