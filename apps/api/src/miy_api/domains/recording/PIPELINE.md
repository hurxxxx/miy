# Prepared Recording delivery protocol

This is local, inactive preparation of Recording's existing four tasks. The
HTTP producer still uses the legacy Canvas chain. No setting, discovery result,
schema version or incoming message activates the official worker profile. This
work does not install a service, publish to an operational broker or prepare an
operational database role.

The source owns `recording_stage_commands`: immutable original source, attempt,
stage, payload digests and stamped producer identity, plus a durable execution
token. Core owns `core_recording_publications`: immutable command/route/issuer
binding plus publication observation. Core can read the exact source needed to
render the fixed body; it cannot modify Recording or source commands. Source can
read the binding but cannot publish or write Core receipts. These records are
separate from projection events and ordinary Recording publication-to-app data.

`create_managed_recording_attempt` is an explicit internal source entry point
with no HTTP binding. It checks current source authority, owner/app admission,
saved audio and absence of an active attempt, then commits the attempt and first
command together. The caller is a prepared source composition, not an anonymous
or user-controlled task payload. An uncertain COMMIT does not cause another
write or publication.

`transcribe → analyze_transcript → verify_transcript_summary → persist_result`
is the only stage sequence. Managed delivery uses the same task names, arguments,
return values, execution deadlines and final task ID. It sends one immutable
signature with `miy_recording` header, the isolated
`miy.official.meeting_transcribe` route and no Canvas successor/link/errback.
The final task ID remains the original attempt UUID. Canvas child metadata is
not an authoritative managed-stage graph.

Before effects, the worker checks command, publication, task ID, attempt,
retry ordinal, route, root/parent correlation, body digest, current source and
ACL. It commits pending→running with a fresh token. Source ownership→Recording
→result→command is the lock order. Every durable progress handoff reacquires the
same Session's source locks and checks the original execution token and source
bytes before returning to ASR. No outer connection spans the task, and no lease
deadline or absent process automatically steals a running claim.

The phase's source result, successful command and its one fixed successor commit
together. Permanent provider rejection can finalize failure only with the exact
current claim. Current authority denial, stale input, database error and COMMIT
uncertainty do not become provider failure or task retry. A duplicate running or
terminal delivery does not re-enter the provider or create another successor.

Managed `TransientError` is deliberately not automatic retry permission: current
ASR/gateway errors may follow remote acceptance. The command stays running with
its original token and attempt, with no retry command or new remote call. The
schema reserves a bounded retry transition for a future authoritative no-effect
receipt, but the current adapter does not fabricate that evidence. Legacy
TransientError behavior remains its separate compatibility policy.

## Core preparation and observation

`recording_publications.prepare_publication` makes a single Core binding.
Concurrent preparation converges on the fixed unique command identity using
PostgreSQL conflict handling without overwriting the existing row or send token.
The returned binding is admitted again under the current actual issuer and
producer authority; a conflicting issuer cannot adopt it through this path.
`send_publication` accepts only an explicit prepared publisher callback. It
commits its publication token before sending, then reacquires current producer
generation and its exact publication claim on the same Core Session. Source
business rows are never locked by this sender. The fixed database admission
function uses actual `session_user`, original source principal OID/name,
generation/artifact and ownership SHARE locks; GUC or SET ROLE does not confer
publication authority.

A send exception is unknown. A publication-result COMMIT failure causes no
follow-up write. `reconcile_publication` observes the same IDs and may record
positive source consumption. An absent claim or empty queue is not non-delivery
evidence. Only explicit same-ID republish from observed unknown is supported;
the durable worker claim protects against repeated stage entry. Running remote
work is still not safe to restart.

The operator script has only `poll-once` (prepare at most 20 bindings, **no
send**), `status` and `reconcile-one`. It uses the explicitly prepared Core DB
principal and exposes no broker credential or activation option. It does not
automatically grant roles. The public Celery signature adapter is tested with
synthetic transport only. A real publisher's bounded I/O, acknowledgement and
credential/queue isolation must be proved before an executable composition is
enabled; a Python callback annotation or memory broker is not such proof.

## Compatibility and remaining cutover work

| Message/composition | Behavior in this source revision |
| --- | --- |
| Default privileged legacy HTTP/worker | Existing legacy producer and no-header tasks for unmanaged attempts remain. |
| No header with a persisted managed attempt | Reject before external effects; never infer managed authority from task ID. |
| Malformed managed header/Canvas links/wrong route | Reject; no legacy fallback. |
| Previous restricted source principal | No automatic new permission. Without command SELECT, new worker code fails closed before effects. Exact role replay cannot enlarge it. |
| Explicitly prepared new source principal | Can read command/binding and mutate its admitted command; current app ACL read dependencies still need a separately reviewed service composition. |
| Official split worker/profile | Remains inactive. Preparing source/Core roles is not activation. |

The role/artifact transition is therefore a deployment precondition, not a claim
of universal no-header compatibility. Owned tests may grant exact synthetic ACL
SELECT dependencies to exercise real app authorization; this does not add those
permissions to the product's source-principal helper.

The new worker's no-header existence check also requires the new command table.
An old schema is not compatible with this artifact and is not silently treated
as legacy. The migration has only been applied to owned test databases; no shared
operational database was migrated. Before deploying this artifact, an explicitly
authorized expand/schema step and matched principal preparation are required.
The user's server restart is separate from deployment of this uncommitted source.

Remote receipt/idempotence/cancellation, explicit recovery of running unknown
effects, executable bounded broker composition, Beat ownership and rollout of
matching producer/consumer roles remain essential. Existing legacy pending
attempts are never silently migrated into this protocol. History-preserving
downgrade refuses populated command/publication records. No runtime status here
means that an official service has been activated or deployed.

## Database authority and role preparation

`recording_managed_20261007` follows `docs_legacy_repair_20261007`. It adds the
two protocol tables without changing the existing 88 business source tables.
The guarded Source inventory is 90: those 88, append-only
`official_projection_outbox`, and mutable `recording_stage_commands`. Core
publication rows are outside that Source inventory. The migration grants no
runtime-role permission and does not prepare or activate a consumer.

Upgrade validates the exact homogeneous preceding 89 statement guards before
DDL. If they are already hardened to actual-role guards, ownership must first
be `draining`; active or mixed/disabled/malformed guards refuse the transaction.
The new command receives the same preceding guard kind, preserving the fenced
inventory. All earlier migrations remain immutable. Empty legacy schema
roundtrips preserve Recording data. Hardened downgrade requires explicit
retirement, and populated command/publication history refuses downgrade even
after statement-guard retirement. No implicit history deletion is available.

Core administration explicitly calls `prepare_principal` for a supplied Source
LOGIN role and `prepare_core_principal` for a different supplied Core LOGIN role
in its own clean, non-autocommit READ COMMITTED transaction with current actor
authority and exact ownership CAS. These helpers do not create roles, handle
passwords, repair ambient privileges or run during application startup. New
preparation requires the complete migrated guard inventory and fixed private
function contracts before any grant. Effective membership, ownership, column,
PUBLIC, sequence, function and creation authority are checked; an unexpected
privilege is refused rather than revoked automatically.

Source receives command SELECT/INSERT/UPDATE and Core-publication SELECT, with
no command DELETE/TRUNCATE, Core mutation or admission-function EXECUTE. Core
receives only the fixed Recording/result/command reads, publication
SELECT/INSERT/UPDATE and the fixed admission-function EXECUTE; it has no source
DML or source row-lock grant. Existing Source principal exact replay is
metadata-only: it does not add command or publication permissions or emit a new
preparation audit. A new artifact/generation uses a newly prepared principal;
old connections remain fenced after the explicit ownership transition.

SQL derives producer/issuer identity from actual `session_user` and role
OID/name. It stamps provenance, rejects immutable identity changes, retains the
execution token after claim and refuses history DELETE/TRUNCATE, including
direct SQL and COPY paths. Fixed schema-qualified functions use private
`search_path`, with no PUBLIC EXECUTE. A recreated role name, GUC or SET ROLE
cannot adopt an old binding or producer identity.

`miy_recording_publication_admit(uuid,uuid,text)` locks current ownership and the
original producer principal SHARE before the exact publication FOR UPDATE.
The caller keeps those locks on the same Core Session through the bounded send
and observation; drain or producer revocation waits for that transaction.
After it finishes, stale authority refuses another admission. SQL checks READ
COMMITTED, while Python additionally rejects client-side autocommit; the SQL
function alone cannot enforce a driver's transaction lifetime.

Owned PostgreSQL tests exercise genuine separate LOGIN roles, stale authority,
drain blocking, guard tamper, COPY/provenance, immutable history, old-principal
grant preservation and 89→90 transitions. These tests do not establish full
operational service authority: app-admission/ACL read dependencies and broker,
Beat, credentials, transport deadlines and remote-effect recovery still require
the explicit matched service composition described above. No operational role,
shared database or service has been changed by this local validation.
