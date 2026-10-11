# Files prepared Core projection

This is an inactive internal composition for consuming canonical cached Files
artifacts without writing Files Source. Ordinary legacy adapters and callbacks
keep their existing extraction behavior. It is not a Source extractor, a service
cutover or a provider activation switch.

## Cached artifact and actual event

`prepared_core_file_projection(db, projection_event=actual_ref)` scopes a trusted
internal Session to one existing Core reference. It selects delivery, never
SQL, app/actor/ACL or provider authority. No public request, environment switch
or global Session factory selects it. Every read uses
`require_prepared_core_file_projection_event` to compare the complete persisted
Core event and current head using SELECT only. A supplied reference or resource
cannot escape the typed context. Deleted references may have no checksum.

`load_ready_file_rag_projection(db, file_id=..., expected_checksum=...)` reads
canonical Source extraction fields and uses the existing pure projection builder.
It never reads object storage, parses/OCRs, flushes/commits or writes Source.
Source missing/deleted alone returns `None`. Active pending, failed, unsupported
or an event awaiting a checksum raises `FileArtifactNotReady`; malformed or
oversized ready fields raise `FileArtifactInvalid`; exact expected/event/artifact/
current external content checksum conflict raises `FileArtifactChecksumMismatch`.
Stable code/reason controls contain no artifact or provider response text.

Reads disable autoflush, refresh actual rows and explicitly load only owner
`id/display_name/full_name`, corpus `id/access_scope_kind`, and nine safe external
metadata/checksum columns. Other fields/relationships use raiseload. The fresh
role's exact read closure is provided separately by
`official_apps.file_projection_roles.prepare_file_projection_reader`; it grants
no Source DML/row lock, credentials, provider, partition/job mutation or full
worker authority. Current serving ACL, app availability and the worker's mutation
fence remain independent checks. This reader profile alone cannot execute the
whole worker or current Source HTTP service.

The complete canonical artifact budget is 4 MiB; top text/block text/row text each
240,000 characters; 4,096 blocks/rows; 16,384 cells; field strings 4,096 characters;
metadata 64 KiB/depth 8/nodes 4,096/keys 1,024/key 128. Identity, unique nonempty
block IDs, meaningful evidence, finite JSON values and UTF-8 are validated.
Metadata cannot override builder-owned Source/checksum/link/scope fields or the
existing safe external field contract. Oversized historical output is refused
without truncation or rewriting. Bounded current plain/HTML parser artifacts are
compatible; parser policy and the legacy builder are unchanged.

`files.artifact_contract.validate_file_extraction_artifact` owns this pure bounded
raw-field validation for both Source and Core. It imports only standard library
and the existing EvidenceBlock data contract. Legacy/Core artifact, error and
external safe-key names reexport the same objects. This shared validator supplies
no Source status, current input, actor/ACL, event/head or compute admission.

The reader verifies the Source file pointer and accepted/current event consistency.
It does not lock corpus or partition lifecycle. Historical ready artifacts lack a
captured storage-key/result fingerprint; these reads do not retroactively attest
current immutable input or claim backend readiness.

## Strict Source correlation for prepared materialization

The separate `materialization_source.py` read entrypoint requires the typed
prepared context and an actual safe PostgreSQL LOGIN with READ COMMITTED and
driver autocommit disabled. After transaction admission it sets the lookup
namespace locally to `pg_catalog, public, pg_temp` before catalog identity and
model reads, so temporary same-named tables cannot shadow existing canonical
public tables. The setting lasts only for the caller transaction and grants no
data or role authority. Membership, elevated flags and any registered Source
principal matched by OID or retained name refuse. Preparation metadata and GUCs
cannot replace runtime identity. The fresh role preparation contract belongs to
[FILE_MATERIALIZATION.md](../official_apps/FILE_MATERIALIZATION.md); existing
cached-reader and ingress roles are not expanded.

`require_current_file_materialization_source` compares the complete persisted
Core event and current head, then joins the latest genuine Source stream event
to its receipt. Exact Source event/revision/digest/resource correlation and an
accepted receipt for this exact Core event are required. Missing, unaccepted or
superseded tips hold. A newer unaccepted result with the same raw SHA cannot be
read under an older accepted event.

`load_prepared_file_materialization` reads one bounded scalar snapshot using
File17/public owner3/corpus3/safe external metadata10. It verifies active Source
state, current output stamp, exact File/corpus partition and external checksum
bindings and the shared artifact budget. The existing keyword and vector
builders receive that same snapshot and retain the same result stamp and exact
Core partition/version. An active event with missing/deleted Source holds;
only an accepted deleted event with current missing/deleted/unsupported Source
may return a deletion pair.

`require_unchanged_file_materialization` rereads complete event/head/latest
accepted Source correlation and current output/binding identity after loading
and at later composition boundaries. These reads take no locks and grant no
effect authority. Source-stream then Core-head locking, partition lifecycle,
provider admission and durable retained unknown effects remain required for the
future effect composition. Arbitrary legacy/direct body writes are not
retroactively attested by the event witness; controlled-generation writer/worker
quiescence remains an activation gate. No parser, storage, Source write,
flush/COMMIT or provider is invoked by this helper. The old cached reader and
generation/worker paths remain separate compatibility compositions.

`require_file_materialization_identity` exposes the same fixed transaction,
namespace and actual-role admission before batch discovery or historical/empty
reconciliation reads. It needs no current-event context and grants no effect
authority. The separate inactive effect composition belongs to
[FILE_EFFECT_EXECUTION.md](../retrieval/FILE_EFFECT_EXECUTION.md).

## Worker phases and callback ownership

The existing three-argument Files adapter selects the cached reader only inside
the typed prepared context. The prepared worker validates the actual event and
current head before `_rag_runtime_for_job`, provider construction or a backend
call. A DELETE job must reference an actual deleted event; a live active event
cannot authorize an explicit DELETE. An UPSERT whose actual Source row is missing
or deleted retains the existing derived-only missing-projection delete behavior
under the original Core event and mutation fence.

Only a control error wrapped by the explicit preflight proves no effect. It holds
the same job/event in `FAILED`, refunds the claim attempt and clears retry time.
Pending, failed, unsupported or invalid cached artifacts therefore cannot delete
vectors or record a Source extraction failure. A control error raised later,
including after a backend delete or callback, is `file_projection_effect_unknown`:
the same job/event and attempt remain, with `FAILED` and no worker/provider retry.
Both outcomes require explicit recovery or genuine later Source readiness work.
They are not success or a promise that a remote effect stopped.

If the hold COMMIT or subsequent observation is unacknowledged, a private typed
control returns `file_projection_hold_commit_unknown`, bypassing the ordinary
failure handler and task retry. It performs no second failure/pending write,
Source callback or provider call. A rollback attempt cannot establish whether
COMMIT succeeded. Observe only the same job/event: an acknowledged `FAILED` row
is not Beat-claimable; an uncommitted hold can leave the original `processing`
claim in the database, which legacy expired-claim recovery may later discover.
Operational effect admission and authoritative Beat ownership remain activation
gates. This local catch does not block every live scheduler or crash recovery.

Prepared ready callbacks revalidate the actual event/current head and cached
checksum, then stage only a Core keyword UPSERT carrying that actual event.
They cannot emit or repair a Source intent, change canonical extraction fields or
read storage. Prepared deletion callbacks never purge Source artifacts; failure
callbacks never mark Source extraction failed. Keyword enqueue suppresses immediate
after-commit publication for both new and merged pending rows. Durable pending
work can still be found by a future scheduler; this is not an operational queue
quarantine. No automatic publication, task registration or runtime profile is
enabled here.

## Prepared Files Core ingress

Fixed pending/ready/delete Core staging and same-event observation are owned by
the [prepared Files ingress contract](../official_apps/PROJECTION.md#prepared-files-core-ingestion).
That separate capability and minimal staging role do not grant Source extraction
or user-serving authority. Closed gates accept only validated control
head/event/receipt with no derived jobs; a receipt never establishes index
readiness. Existing first-three Source discovery and legacy composition are
preserved.

## Current result admission in serving

`files.current_content.load_current_file_content` reads only current
id/deleted_at/extraction_status/extraction_content_checksum/
retrieval_partition_id/extracted_at columns under no-autoflush. It returns an
immutable witness for undeleted, ready, valid-SHA results. It bypasses cached ORM
state, performs no Source/Core write or storage/provider read and grants no ACL.
Empty candidate sets perform no SQL.

`file_candidate_matches_current_content` requires the candidate's original SHA,
partition and Source result stamp. `file_extraction_result_marker` normalizes the
existing `extracted_at` to UTC ISO microseconds with `+00:00`. Raw input SHA may
remain unchanged when re-extraction produces different text. Missing or changed
result stamps fail closed. A legacy None partition matches only a current Source
None partition. Current values never replace a missing or stale candidate
envelope. This checks Source/candidate consistency, not cryptographic integrity
of arbitrary backend text or immutable object provenance.

Keyword/vector builders retain the Source stamp. Vector hydration promotes the
admitted projection envelope into query-hit metadata after chunk fields, so
chunks cannot replace it. Routing hydration reads only required File/corpus/safe
external metadata fields and rechecks content after hydration. Current app
admission and Source ACL remain independently required. Keyword applies this at
each bounded refill page and before final facets/snippets. RAG applies it before
refill/rerank and again before final ACL/grounding, for legacy and partitioned
Files composition. Common retrieval repeats the check before AI input and final
use. Files search/chat check again after Source hydration/ACL; search refills the
bounded window and recomputes `has_more` after stale candidates are removed.

Older indexes without the result stamp require explicit reindexing and verified
coverage before service cutover. No automatic backfill, bootstrap, registration,
gate activation or privilege expansion follows from this helper. The staging
Core profile, cached-reader profile and current-serving read closure are
separate capabilities.

## Remaining Source and operational gates

The inactive existing-bound/pending local Source command is now implemented under
the separate [Source extraction owner](SOURCE_EXTRACTION.md). That owner defines
the fixed request/claim/input/result, current authority, fresh outer transaction,
terminal correlation and history-only observation. Core acceptance and worker
execution do not call that Source command or receive compute authority from its
receipt. Historical legacy ready artifacts are not retroactively proven to have
the new captured-input provenance. Unknown remote computation still needs its own
same-request receipt before automatic recovery; the current OCR endpoint does not
supply that contract.

Upload/replacement must produce a genuine pending Source event to advance the
fence. The fixed Core ingress stages no keyword/vector extraction work for
pending/no-checksum. Immutable storage publication, complete Source bootstrap,
Files aggregate/tree serialization and managed corpus allocation/lifecycle
remain required. The legacy reverse writers remain in the
ordinary composition pending the matched Source command/service cutover.
These are required structural gates, not optional app feature issues.

The [official projection owner](../official_apps/PROJECTION.md) and
[worker runtime owner](../../../../../worker/README.md) retain the wider
authority, publication, routing and service activation contracts. No role from
this preparation is silently installed in a running service.
