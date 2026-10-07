# Files prepared Source extraction

This inactive internal composition prepares extraction of an already bound Files
Source object, reads it through the owned bounded storage reader, computes with
the existing local parsers, and atomically records canonical Source fields and a
genuine Source projection intent. It adds no public endpoint, startup activation,
worker task, broker publication, provider or operational role configuration.

## Fixed input and authority

`extraction_contracts.FileExtractionRequestSpec` retains distinct request, result
and reserved result-event UUIDs. The original authenticated execution reference,
actor, parser policy and compact request digest are immutable. The fourteen-field
input snapshot contains the current File binding, storage descriptor, timestamp,
safe external version/checksum and the actual latest pending Source event ID and
digest. No new pending event or fourth UUID is manufactured. The first policy is
`files-retrieval-v2/local-only-10m-v1`, capped at 10 MiB at capture/prepare and at
the actual storage reader; the legacy extractor keeps its 120 MiB default.

The File must be pending without an extraction checksum, with a non-null existing
partition binding and a genuine latest active/upsert/no-checksum Source intent.
Core allocation and acceptance are separate. Native and managed objects use the
existing public Files resource ACL rules. Retrieval metadata never grants access.

Every stage verifies the actual PostgreSQL session principal and current Source
generation through the narrow fixed `miy_file_extraction_admit` capability. It
then reads the current actor, company app admission and Source ACL. The original
execution reference identifies a trusted Core-authenticated session; it is not a
credential or a new authentication protocol. Current AuthSession reads are limited
to ID, actor, expiry, revocation and impersonator. Impersonation is refused. Active
operations require the original execution and producer. Expiry uses the actual
current clock, including after lock waits and after storage I/O.

Before these unqualified ORM reads, each fresh stage installs transaction-local
`search_path = pg_catalog, public, pg_temp`. This makes pooled TEMP relations
unable to shadow actual AuthSession, app/ACL or Source rows. It changes no global
role setting or TEMP privilege; the admission capability itself remains publicly
qualified and the private functions retain their owned namespace.

## Transaction and storage ownership

The public internal command stages require a fresh, clean outer READ COMMITTED
Engine-backed Session. Connection-backed binds and external join modes are
refused before autobegin or Source SQL. The fixed Source, actor/session, company
app, folder/File grant, group and PMS team query models must all resolve through
public `Session.get_bind(mapper=...)` and `get_bind(clause=select(table))` to the
same default Engine. Per-model/table routes to another Engine or a borrowed
Connection are refused before the runner acquires ownership, SQL or cleanup.
An explicit route to that same Engine remains supported; dynamic routing to
different database resources is outside this fixed composition.
Existing caller transactions, pending ORM
changes and nested/savepoint transactions are refused before Source SQL and are
preserved. Command stages and the runner use the same non-SQL Session validator;
the runner acquires ownership only after it passes. A rejected borrowed Engine,
Connection-backed or unbound Session is neither closed nor rolled back, and its
pending ORM state remains caller-owned. Session shape validation grants no
Source/user/app/resource authority; actual Source admission follows separately.
A stage that itself started a fresh outer transaction rolls back its own failed work; rollback
cleanup cannot prove an outcome or replace the original stable control. Commands
never COMMIT. Only `FileExtractionRunner` creates, commits and closes each fresh
owned Source Session. No borrowed Session or unrelated flushed work is committed.

Source authority SHARE, File/current binding row locks and the resource stream
lock remain held during the trusted storage read and input-bind COMMIT. The
existing `selected_storage.read_selected_object` supplies bounded GET, exact size,
timeouts, response close, no redirect/retry and private signed-URL handling. The
runner accepts no caller-provided bytes or URLs. Only the pure parser runs outside
DB locks, after the input-bind acknowledgement. A caller already running an async
event loop is refused before any Session, claim, storage or write; there is no
automatic thread fallback.

## Claim, compute and atomic result

States are prepared, claimed, input_bound, and terminal ready/unsupported/failed.
The original live runner may consume one newly acquired token claim. Exact token
replay returns history and grants no storage read or compute. There is no automatic
claim stealing, takeover, reparse or retry. A claim ACK lost in that original live
frame permits only one same-ID observation before continuation; input-bind ACK
uncertainty may use only that frame's retained bytes after observing the same SHA
and byte count. Process loss leaves the durable claim for explicit reconciliation.
Low-level caller-owned stage primitives are internal trusted composition; their
receipts alone do not confer the runner's live-frame compute authority.

The local parser calls `extract_file_artifact(..., allow_ocr=False)` and the shared
pure `artifact_contract.validate_file_extraction_artifact`. OCR need becomes an
input_bound hold with reason `ocr_required`, before provider inspection. The
legacy `allow_ocr=True` default remains intact. No remote OCR is started here.

Ready writes canonical text, blocks, metadata and the bound input checksum, then
appends the retained genuine active event. Unsupported clears the artifact and
appends its genuine delete intent. Failed stores a stable local parser failure
and creates no event; it neither manufactures ready data nor requests deletion.
Current session, app and resource authority is checked again after the event-ID
lock and actual intent append, before the terminal digest and history write. A
revocation during that wait rolls back the already flushed File and intent.
The result digest is computed by the fixed Source SQL helper over its owned
PostgreSQL envelope. Python compact JSON is used only for request/input digests;
it is not assumed equal to PostgreSQL JSONB text serialization.

Canonical File changes, terminal request digest/history and ready/unsupported
intent are one outer Source COMMIT. The fixed request BEFORE guard and initially
deferred terminal AFTER check verify the File, intent and request's current
top-level transaction correlation and final result state. A separate private
seal prevents further File update/delete, same-stream outbox insertion,
SourceMetadata insertion/update/delete (both old and new File bindings), or
corpus binding/scope update/delete once that File has a terminal request in the
same top-level transaction. The seal remains effective when the caller makes
constraints immediate. Later transactions may legitimately change Source data;
the immutable receipt records the historical outcome. The private five-function
and eight-trigger bodies/inventory are attested; the minimal owner/read closure
and two Source EXECUTE grants are unchanged. A successful flush remains
provisional until COMMIT is acknowledged. Any actual post-flush refusal rolls
back File, history and intent together.

## Uncertain acknowledgements and immutable history

COMMIT failure, including `BaseException` cancellation, returns
`FileExtractionCommitUnknown` with the retained phase and
same provisional IDs, token, input witness and, for terminal apply, result digest.
Cleanup does not decide whether COMMIT occurred. Database errors and validation
controls leave this internal runtime through stable identifiers; raw SQL,
parameters, object keys, extracted text and provider responses are not logged.
Close/rollback cleanup preserves the original control or acknowledged result and
never issues another read/compute permit. Cleanup also isolates `BaseException`:
a rollback/close cancellation cannot mask an original refusal/unknown receipt or
downgrade a known COMMIT ACK. Stage body database/validation sanitation remains
unchanged; cancellation of COMMIT is classified by the owned runner.

Terminal body-submitting apply always refuses with
`terminal_observation_required`. No historical result body is duplicated or
recomputed against the current File. Separate `observe_file_extraction` compares
retained result ID/digest, token and input witnesses, then returns immutable
history without File or intent writes. An observer may supply a newly
Core-authenticated current session for the same actor; the expired/revoked original
execution remains provenance. Another actor or execution delegation is refused.
An uncertain apply is observation-only, with no automatic parser or apply retry.

## Explicit current workset observation

`source_extraction_bootstrap.FileExtractionBootstrapWorkset` supplies the current
authenticated actor/execution and 1..100 explicit File IDs. The command revalidates
even an already typed workset before Source SQL, then sorts and deduplicates IDs.
It is a finite current selection; it has no cursor, SKIP LOCKED or whole-store
completeness field. A locked or newly committed lower ID is not permanently
excluded by a remembered high ID. Selecting more objects remains an explicit
caller decision, rather than an automatic full-store scan.

`probe_file_extraction_workset` starts one fresh caller-owned Source transaction.
It discovers the bounded File/corpus associations, locks every distinct Source
corpus SHARE in sorted order before any File lock, and then locks sorted Files.
Rediscovered associations must equal the captured association: an unexpected
corpus is refused before taking its SHARE lock, and the File association is
checked again after the File lock. This follows the corpus-before-Files order of
aggregate/tree writers. No Core partition allocation or descriptor read occurs;
the existing Source binding is not a Core lifecycle admission claim.

Every member uses the genuine current pending input and public Source ACL. The
command checks each supplied File's current actor/session/app/resource authority
again after the entire selection's last Source lock, including a later member's
wait. A missing, changed, unauthorized or non-pending member refuses the stage;
the command returns no partial completion claim.

Existing requests match exact File ID, current fourteen-field input fingerprint
including pending-event UUID/digest, and fixed parser policy. Own observations
validate the retained canonical request/spec and original three UUIDs. They can
be unrequested, existing_prepared, existing_bound or historical existing_terminal;
existing receipts always have `newly_acquired=False`. Claimed/input-bound/OCR-held
state is no new storage-read or compute permit. An old-input request never covers
different current input. Normal ready/unsupported/failed Files are outside this
pending-only probe; their immutable history uses the separate observer above.

Another actor/execution's matching request yields only the supplied File ID and
`reserved_other_execution` status. Its input, spec and receipt are all None:
no request/result/event IDs, digest, storage key, actor/session or body is exposed.
Private own fields are omitted from the member's repr too.

The probe creates no request, event, UUID or job, reads no object bytes and invokes
no parser/provider/publisher. Preparation remains the explicit existing F2 API
with a caller-retained three-ID spec. Stage observations are provisional. The
fixed `FileExtractionRunner.probe_bootstrap` wrapper clears that flag only after
its fresh owned Session's COMMIT ACK, including own member receipts. Lost ACK
retains the private provisional observation and `bootstrap_probe` phase, without
automatic retry, preparation, claim or compute; cleanup cannot replace it. An
absent request or read-only probe is no global completion or failed-COMMIT proof.

## Remaining integration gates

This is a bounded prepared internal protocol. It does not complete Source HTTP
authentication/composition cutover, immutable storage provenance, operational
principal provisioning, remote OCR result delivery, durable full-store workset
membership, controlled materializer latest Source/Core event provenance,
effect/Beat recovery, production activation or deployment. Prepared Core Files
pending/ready admission is separately owned by
[Prepared Files Core ingestion](../official_apps/PROJECTION.md#prepared-files-core-ingestion);
the Source probe does not invoke it. Source terminal success means canonical
Source result and a pending genuine intent; it does not mean Core receipt, jobs,
keyword/vector readiness or serving authorization.
