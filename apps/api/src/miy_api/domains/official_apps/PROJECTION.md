# Official source projection transport

This is a fixed contract for `docs_native_doc`, `pms_task`, `meeting`, and
`file_manager_file`. It adds no new autonomous consumer, service activation, API authority,
retry engine, or arbitrary event type. The official service remains inactive.
The 88 business source tables remain a separate inventory from the one new
suite transport table.

## Transactions and identity

`append_projection_intent` writes an immutable `official_projection_outbox`
record in the caller's original business transaction. The producer allocates
one UUID for the business event and retains it when reconciling an uncertain
commit; an explicit replay must have exactly the same canonical payload and
SHA-256 digest. It must not repeat the business mutation to discover whether
an acknowledgement was lost. The Python producer requires an actual
READ COMMITTED transaction and obtains the existing source writer guard.

Each resource has a separate source revision. A transaction advisory lock
serializes that stream before reading its persisted tip. A unique constraint
and a row trigger enforce the next revision, payload digest and resource
identity even for direct SQL/COPY inserts. An additional UUID lock prevents
cross-resource reuse of the same event ID from racing. The SQL trigger stamps
the actual `session_user` role name/OID and current ownership generation and
artifact. Caller-supplied producer identity is overwritten. This does not make
an arbitrary SQL client automatically couple a business mutation to an event;
that same-transaction discipline belongs to the owned source producer.

The source revision is **not** the existing Core `projection_version` or
`event_sequence`. Already deployed Core heads and generation watermarks keep
their own versions. The new source stream starts at revision 1 without
resetting a Core head.

## Core acceptance and current authority

`retrieval.official_projection_ingress.accept_projection_intent` is an
internal Core function, not an authenticated-user endpoint. The actual login
principal must have Core receipt/projection privileges. It validates the
persisted canonical event and expected digest, serializes its resource stream,
and accepts an exact existing receipt without producing another Core version.
A missing earlier receipt rejects a later revision. If a newer committed
source event already exists, accepting the earlier event records a
`superseded` receipt and does not change the Core head. This prevents an old
upsert from undoing a tombstone.

For the latest event, acceptance resolves the existing source-owned partition
adapter. The partition must currently exist, be active, have the fixed source
namespace and allowed candidate scope, and match the committed source binding.
A hard-delete intent may outlive its row; its namespace remains fixed and an
existing Core head must agree on the partition. A live row can also emit a
tombstone immediately before hard deletion within the original transaction.
An active event for an absent source is rejected.

These checks observe current committed source metadata. They are not an ACL
grant or an atomic lock over every source ACL/partition mutation. Existing
search authorization still re-evaluates app admission, role, current partition
and source resource ACL before returning results. Existing search/RAG jobs
retain projection head/version checks and generation watermarks. Changes that
bypass the canonical source event path remain explicit migration gaps below.
No synthetic user, guessed visibility, or ready state is created.

Acceptance creates the existing Core projection head/event, the existing
search/RAG jobs, and an immutable `official_projection_receipts` row in the
same caller transaction. It never commits internally. Any error requires the
caller to roll back the entire transaction. After an uncertain COMMIT, query
or accept the **same event UUID**; receipt absence means only “not observed in
this read”, not proof that an in-flight commit cannot complete.

`pending_projection_intents` returns at most 100 records absent from the
receipt table. Ordering is only a convenience: there is no high-ID or
high-timestamp cursor that could skip a lower/earlier event committed later.
There is no autonomous dispatcher or automatic retry in this slice.

## Existing application behavior

The default legacy composition's four canonical hooks use an emit-then-accept bridge in their
original outer transaction. Docs retains keyword indexing and configured RAG;
its existing visibility operation keeps the historical content event kind
while recording `visibility_update` for RAG. PMS and Meeting retain keyword
jobs. Files still records its projection event when its retrieval gate is off;
when enabled, extraction precedes keyword indexing and deletion creates the
existing keyword/RAG work. Core repair/adoption/reindex functions remain Core
operations. Publication is still after the acknowledged outer commit through
the existing job machinery, not a new transport.

Docs grant creation/update, meeting-grant revocation/expiry changes, and meeting
document visibility fan-out now use that same canonical source intent. Grant
rows, source intent, Core head/event/jobs and receipt belong to the original legacy
caller transaction. Batch fan-out sorts and deduplicates document IDs; explicit
IDs captured before meeting detach/delete remain usable after its associations
are removed. The source-owned visibility helper refreshes the document under a
`FOR NO KEY UPDATE` row lock before choosing its operation. This excludes
concurrent content/trash changes while remaining compatible with grant INSERTs'
foreign-key `KEY SHARE` locks; the helper never changes a document primary key.
It does not promise that every multi-resource transaction is deadlock-free:
database errors still abort the whole caller transaction without automatic
business retry or self-acceptance. Missing documents are skipped; a
trashed document emits deletion work and cannot become an active visibility
head through this path. The source partition stays unchanged, and original
query-time admission/resource ACL and grant-expiry checks remain authoritative.

New meeting visibility changes no longer create a scope-only
`RagVisibilityRecomputeJob`: each affected document directly gets its versioned
keyword work and, when RAG is enabled, versioned RAG work. Previously queued
scope jobs and unversioned Docs resource jobs use the fixed Core compatibility
path below. The source producer still neither installs an independent consumer
nor allows source-only credentials to execute the emit-then-accept Core bridge.

## Migration and least privilege

`official_projection_20261007` follows the frozen
`official_source_writer_20261007` migration. It checks the exact homogeneous
88-table writer inventory and existing ownership under lock, requires READ
COMMITTED, and adds the same statement guard to the source outbox. A hardened
installation must be draining. It performs no role grant or activation.

The current explicit principal preparation checks all 88 source guards plus
the transport guard, private fixed-search-path stamping function, and immutable
outbox/receipt triggers before any new grant. A new generation's role receives
only SELECT/INSERT on the transport, alongside its existing source DML. It
cannot update, delete, truncate, disable triggers, write Core receipts, or
write projection heads/events/search/RAG jobs. Old principal exact replay
performs no additional grant; upgrading a hardened database requires explicit
new principal preparation, guard validation, old-role revocation and the
existing ownership CAS sequence. No production role is provisioned here.

Both transport and receipt are append-only, including TRUNCATE rejection.
Schema downgrade refuses nonempty records and refuses hardened guard retirement
without the existing explicit operator transition. There is no automatic
retention deletion or schema downgrade. A future retention/backup restoration
procedure must preserve immutable IDs, payloads, receipts and role provenance;
ordinary source credentials cannot perform it.

## Prepared Source-only company projections

`projection_delivery.prepared_source_projection(db)` is an explicit internal
composition for one Session and exactly Docs/PMS/Meeting. It does not configure
the global engine/session factory, infer authority, grant privileges, expose an
HTTP setting or remove the inactive service gate. Ordinary Sessions retain the
legacy bridge. Actual Source role/guard admission remains mandatory; an arbitrary
`db.info` flag, manifest, header or transaction GUC cannot select this composition.

In that composition, Docs partition binding and PMS/Meeting creation/hooks call
the fixed Core company-default UUID capability below. Source writes only its
pointer, business rows and genuine immutable intent in the original transaction.
Missing, inactive, wrong namespace/scope, nondefault or changed bindings fail
without Core allocation or privileged fallback. Private Docs keep the same stable
company candidate partition; ownership, sharing and current resource ACL remain
Source contracts. Docs visibility and Meeting-to-Docs fan-out use the same
prepared Session. Original user/app/resource checks are not replaced by delivery.
The existing Source role still lacks complete HTTP auth/admission/audit access;
these prepared internal paths do not claim a deployed independent API service.

`emit_source_projection` returns a genuine immutable `SourceProjectionReceipt`
with event UUID, Source revision, resource identity and payload digest. It never
returns a Core projection version or sequence. Canonical enqueue hooks return
None, and the prepared context records up to 100 provisional receipt identities.
Exceeding that bound fails the caller operation; it is not partial fan-out success.
Receipts remain provisional across savepoint/outer rollback until their actual
Source row is observed after outer COMMIT. The local journal is not a durable
business idempotency ledger. A caller supplies/retains the event UUID once and
uses `lookup_source_projection_receipt` after unknown COMMIT; one absent read
cannot justify rerunning business work. Whole-process request-state loss is a
remaining business recovery boundary, not permission for automatic retry.

Core setup is `prepared_company_partitions.prepare_company_projection_defaults`.
It checks actual Core metadata authority, current administrator and exact current
ownership, prepares only Docs/PMS/Meeting company defaults, validates their
descriptor under SHARE locks and leaves outer COMMIT to its caller. It provisions
no role or runtime and is not startup automation. Retain its returned exact UUID
tuple before COMMIT. After unknown setup COMMIT, use
`lookup_company_projection_defaults` to read those UUIDs only; changed/retired
identities reject, missing means unobserved, and no replacement is allocated.
Calling the allocator again is not setup reconciliation.

`retrieval.official_projection_consumer.consume_projection_once` stages one
persisted event in a caller-owned Core transaction. Its prepared acceptance
wrapper locks current company metadata through Core COMMIT before recording a
latest event; ordinary legacy acceptance is unchanged. Historical exact receipts
and superseded old Source events keep their original identities without requiring
the metadata to remain active forever. Source/Core revisions remain distinct.

`run_projection_consumer_once` owns a fresh Core Session and returns only after
acknowledged COMMIT. Its discovery chooses one oldest unreceipted Source revision
per resource, uses no high-ID/time cursor and sets 5/15-second transaction-local
lock/statement limits before the pending scan. It accepts an explicit same UUID
and digest for reconciliation. Unknown COMMIT returns a bounded control exception
containing that identity; no business operation/provider is retried. The stage
primitive itself never commits; there is no generic helper that commits an
arbitrary borrowed Session or trusts a caller-created receipt value.

Prepared acceptance persists fenced keyword and configured Docs RAG jobs while
passing `publish_after_commit=False` to the existing Core outboxes for both new
and merged pending work. No publication callback is registered or publisher
constructed. The outbox API default remains True for existing callers. This is
not operational quarantine: existing deployed Beat/workers could discover pending
rows in a live database. No shared database is used by this slice; actual service,
queue/profile and old-consumer drain ownership must be completed before rollout.
No consumer task, endpoint, automatic polling or activation switch is added.

## Explicit company-default lock capabilities

`official_partition_20261007` appends two private fixed-search-path SECURITY
DEFINER functions without changing the original 88 business sources, two
transports, Recording guards/history or any prior migration. Migration gives no
role grants and activates no runtime. During an explicit hardened drain,
`install_company_partition_reader` assigns both functions to one separately
pre-provisioned minimal NOLOGIN owner. That owner has principal SELECT, partition
metadata SELECT/UPDATE only for row locks, and EXECUTE on the existing private
producer admission. It owns no other function/table, has no members/CREATE/
sequence/grant-option authority, and cannot log in.

A fresh reviewed Source generation uses `prepare_principal(...,
company_projection=True)` after attestation. It gets only EXECUTE on
`miy_read_official_company_partition(text,uuid)`: actual session_user/OID and
current immutable principal/legacy ownership generation/artifact acquire SHARE
admission; the fixed Docs/PMS/Meeting active company default is locked FOR SHARE
and only its UUID is returned. Source receives no Core partition SELECT/DML/
row-lock permission or Core lock capability. Existing principal exact replay
returns before new GRANT/audit, so an old role is never upgraded implicitly.
Before any fresh Source/Core profile grant, attestation checks both functions'
PL/pgSQL language and exact body SHA-256 against the owned frozen migration,
alongside signature, result, search path, private execution and minimal owner.
An altered body with the same function header is refused without new grants.

`prepare_company_projection_core` grants a separately supplied safe Core LOGIN
fixed Source/outbox/partition SELECT and receipt/event/head/search/RAG staging
permissions, one event-sequence USAGE and EXECUTE on
`miy_lock_official_projection_partition(uuid,text)`. Actual Core receipt/head/
event authority is checked; the exact active company partition is locked FOR
SHARE through Core COMMIT. Existing valid managed-company descriptors remain
supported. Source identities/unsafe role attributes/effective privilege drift
are refused. Source read and Core latest-event lock are distinct; no Source
principal gets Core EXECUTE. A table owner is not assumed to have function
EXECUTE after private owner assignment.

These capabilities grant no user ACL or ready state. Python requires a real
READ COMMITTED non-autocommit outer Session; SQL can inspect its server
transaction isolation but cannot detect the client's DBAPI autocommit setting.
Source and Core SHARE locks end at their respective COMMIT/rollback; later
lifecycle changes can still make a pending intent unavailable. KEY SHARE would
not exclude non-key state/metadata updates. Exact historical receipt
reconciliation does not rerun Source work. Explicit capability grants require
retirement before schema downgrade. All preparation is local/internal, not
installation/startup automation or service/credential deployment.

## Prepared Files Core ingestion

`accept_prepared_file_projection_intent` and
`retrieval.files_projection_consumer` are a separate fixed Files Core
composition. They accept only committed `file_manager_file` Source intents;
the prepared Docs/PMS/Meeting Source resources, their discovery and ordinary
legacy hooks remain unchanged. No endpoint, task, polling loop or activation
setting selects this path. Source extraction belongs to
[SOURCE_EXTRACTION.md](../files/SOURCE_EXTRACTION.md), not to Core acceptance.

For the latest Source revision, Core reads six File descriptor columns, three
corpus binding columns and three SourceMetadata binding/checksum columns. It
never reads storage keys, extraction text/blocks, credentials or user records,
locks Source rows, modifies Source state or invokes extraction. The fixed
`miy_lock_file_projection_partition(uuid)` capability locks the exact current
active company Files partition FOR SHARE until this Core transaction ends.
Live File/corpus/metadata pointers must agree. An active ready intent requires
the exact current canonical SHA-256 and, for managed files, external checksum.
A genuine active/no-checksum tip for pending or failed extraction, including an
OCR hold, records a Core control head/event and immutable accepted receipt with
zero jobs. It neither means ready nor manufactures a deletion. A genuine
delete requires a missing/deleted Source or its canonical unsupported outcome;
a live pending/ready Source cannot be turned into a tombstone by this path.

Ready and genuine deleted outcomes stage the existing keyword and RAG jobs
only when both existing Files retrieval and RAG gates are open. Closed gates
still permit validated control-head/receipt acceptance with no derived work.
An accepted receipt always means control acceptance, never indexing readiness.
Enabling a gate later does not replay that receipt to backfill work; controlled
backfill and old-consumer ownership require separate preparation. Both newly
inserted and merged pending jobs pass `publish_after_commit=False`, so this
composition registers no publication callback and constructs no publisher or
provider. Existing live Beat/workers could still find persisted pending jobs;
publication suppression is not queue quarantine or a deployment procedure.

Files-only discovery chooses one oldest unreceipted revision per resource by
correlated absence checks. It has no high-ID/time cursor and never selects a
Docs/PMS/Meeting event for the Files-only role. Before discovery and acceptance,
the transaction uses 5/15-second local lock/statement limits. Existing Source
stream serialization, revision-gap refusal, exact receipt convergence and
superseded history apply. A superseded revision records no new head or jobs;
an exact historical receipt remains valid after later lifecycle changes.

`consume_file_projection_once` and `observe_file_projection_consumption` are
caller-owned transaction stages and never commit. Their immutable DTOs stay
provisional, including observation of a receipt flushed in the same uncommitted
Session. `run_file_projection_consumer_once` owns a fresh Engine-backed Core
Session and at most one event, and returns a nonprovisional outcome only after
its own COMMIT acknowledgement. Connection-backed joins and existing Session
work are refused before Core SQL and remain owned by the caller. Cleanup cannot
revoke an acknowledged result or replace the retained stable refusal/unknown.

After an unknown COMMIT, retain the same Source event UUID/digest and provisional
consumption. `run_file_projection_observation` uses a fresh owned read-only
transaction to check immutable Source/receipt history and the exact persisted
historical Core event, optionally comparing the retained status/sequence. It
does not accept, enqueue, extract or retry a business mutation. An absent
receipt is only unobserved in that read; it gives no permission to allocate a
fresh identity, rerun extraction or infer that an in-flight commit failed.

`file_projection_20261007` adds only the fixed private partition capability.
Explicit draining installation assigns it to a separate minimal NOLOGIN owner;
the reviewed fresh Files Core profile gets its exact EXECUTE and Core staging
privileges plus the bounded Source descriptor reads above. It has no Source
DML, row SHARE, private File/user/metadata access or Source admission function.
Function body/header/owner/effective privilege attestation precedes grants.
Exact existing-profile replay performs no GRANT/audit; an older company Core
profile is never upgraded implicitly. Source identities, partial/extra grants
and capability drift refuse preparation. Migration/preparation activates no
service or credentials and changes none of the old Source resources or grants.

Current-content/output-version serving and historical-index backfill limits
are owned by [CORE_PROJECTION.md](../files/CORE_PROJECTION.md#current-result-admission-in-serving).
The ordinary Files legacy composition still owns its existing bridge behavior;
this inactive internal composition is not a complete independent Files service
cutover, immutable object publication or durable extraction-bootstrap rollout.

## Core compatibility for previously queued Docs jobs

`docs_legacy_repair_20261007` adds a fixed receipt and normalized target receipt
table. Existing RAG scope/resource dispatch and keyword indexing intercept only
old meeting visibility jobs, all-null-fence `docs_native_doc` RAG jobs, and
all-null-fence `doc` keyword jobs before claim or provider construction. Other
resources use their existing paths. Fully fenced Docs jobs must match the actual
persisted event and keep their original operation; incomplete or inconsistent
fences are refused rather than filled from a newer head.

The Core repair requires a real READ COMMITTED, non-autocommit transaction and
Core receipt/projection privileges. It acquires the same resource source-stream
advisory lock and Core stream/head locks used by source intent acceptance, then
locks and rechecks the original Core job. It reads source rows with ordinary
SELECT only. It does not obtain source row SHARE/UPDATE locks, write source
fields, ensure a default partition, append a source intent, or invent a source
revision. The actual tests use a Core principal with source SELECT only and
confirm source row locks and UPDATE remain denied.

Current source existence/trash, persisted head/event, active company Docs
partition, pending source intent and app/RAG admission are checked before
conversion. An unaccepted source intent, missing binding, partition conflict,
unproven restore or live-source/deleted-head conflict rejects the conversion.
A captured missing document with an existing consistent head yields deletion;
a missing document without that evidence is not an empty success. A live
personal or RAG-excluded document is not made into a Core tombstone merely
because the existing RAG loader excludes it. Query-time resource ACL remains
authoritative; no synthetic actor or guessed visibility is introduced.

Each origin converts at most 100 distinct document IDs in one transaction. The
receipt freezes the exact original input and sorted complete target set. Larger
scopes, malformed cursors, changed input and already-processing origins are
explicitly refused and remain unconverted. A stale processing timestamp does
not prove that an old worker stopped. Before switching deployed workers, old
consumers must be stopped and their processing work reconciled under an explicit
operator procedure. No mixed-version drain or service activation is performed by
this code or migration.

For each target Core records a genuine `repair` event, existing fenced keyword
work, and RAG work when enabled. It does not adopt an arbitrary latest version.
The original job, head/events, replacement jobs and both receipt tables commit
together. The keyword origin leaves `pending` before replacement enqueue so the
pending upsert cannot reuse and then cancel its own replacement. A resource
origin becomes `cancelled` with a replacement reason; a scope becomes
`succeeded` only in the sense that fan-out was durably staged. Dispatch returns
`docs-repair-converted` or `docs-repair-empty`, never an indexing/ready claim.

The two new receipt tables reject UPDATE, DELETE and TRUNCATE. Deferred checks
require the exact complete target set and actual matching repair events. Origin,
event and target-job references use RESTRICT FKs. Core projection events already
reject UPDATE/DELETE under the existing baseline guard; event TRUNCATE RESTRICT
is blocked by references and CASCADE is blocked by receipt immutability. There is
no duplicate event snapshot or new generic event ledger. A legitimate later
pending-job merge can advance the job to another event while the target FK keeps
the accepted historical event intact. Generic retention cannot delete these
origins/events/jobs, and downgrade refuses nonempty repair receipts.

A replay must use the same origin job ID and exact original input. It returns
the accepted target/event identities without recollecting later associations or
creating another repair event. COMMIT or rollback uncertainty raises a bounded
control error and bypasses ordinary worker retry/merge; it does not rerun source
business mutations or call a provider. Receipt absence on one read is not proof
that an in-flight commit will never finish. Reconcile only the same origin.
Transaction-local lock/statement limits are 5/15 seconds, with no automatic
retry. These limits do not promise that every multi-resource operation avoids a
PostgreSQL deadlock; a database failure aborts the whole conversion.

The source stream lock closes the canonical late-commit race without source
UPDATE privilege: a source change that has not acquired the stream lock commits
its later canonical intent after Core repair and advances the head; an already
held source stream makes Core wait and re-read the committed tombstone. Changes
that bypass canonical source producers still remain outside that guarantee.
This migration gives no role new privileges and keeps source guard inventory
unchanged (88 business tables plus the existing source transport).

## Remaining structural work

- Core Docs compatibility is implemented for the three bounded origins above;
  rollout still requires an explicit old-consumer drain, reconciliation of
  processing/over-budget/refused work and coherent receipt retention. No live
  backlog has been migrated by local tests.
- Prepared Docs/PMS/Meeting company defaults and Source-only hooks are separated
  above; their ordinary legacy behavior is preserved. Planner personal defaults,
  Files standalone aggregate locks and managed corpus allocation/lifecycle remain
  required structural work. Source receives no platform partition DML.
- The inactive [Files cached Core composition](../files/CORE_PROJECTION.md),
  [Source extraction commands](../files/SOURCE_EXTRACTION.md) and prepared Files
  acceptance above separate canonical extraction from derived work. Ordinary
  legacy reverse writes remain. Immutable object publication, durable bootstrap,
  complete service/worker composition and controlled old-index backfill remain
  required structural work; no full Files service cutover is claimed.
- Source-only DB credentials alone cannot run all four current application
  services. User identity/admission/resource ACL readers, shared partition
  operations, workers and external effect ownership still need their own
  cutover boundaries.

The local PostgreSQL tests exercise real permissions and transactions. They
do not deploy an independent service or operate real customer object stores,
mail accounts, search clusters or model providers.
