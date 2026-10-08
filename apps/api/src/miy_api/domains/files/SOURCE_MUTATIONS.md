# Fixed Files Source mutations

This inactive internal boundary implements one existing private native root File
soft-delete. It does not change HTTP/default composition or allocate a partition.
The [migration plan](../../../../../../platform-redesign/FILES_SOURCE_AGGREGATE.md)
owns implementation status; this document owns the runtime contract.

## Fixed API and input

`FileSourceDeleteSpec` retains the File ID, original actor/execution, DELETE event
UUID and `FileSourceDeleteExpected` canonical before-state. The expected state
includes bounded identity/storage metadata, extraction status/checksum/stamps,
partition UUID and the genuine active Source tip's event UUID/digest/revision.
It contains no extraction text/blocks/metadata body. Canonical spec is at most
8192 bytes, with strict integers, fixed private/root/native fields, exact naive
UTC timestamp spelling and revalidation of supplied model instances.

`stage_native_root_file_soft_delete(db, *, spec)` supports only the current owner
of a live private File with no corpus, folder, external SourceMetadata or access
grants and an existing admitted default Files partition. Missing/changed state,
tip, binding or unsupported scope is a refusal/conflict. No identity is allocated
and no alternative Core table query is used if the fixed capability refuses.

The caller supplies a fresh single-Engine Source `Session` and owns its outer
COMMIT. Connection-bound/borrowed, active, dirty, nested or routed sessions are
refused before taking ownership; a refusal cannot rollback/close unrelated caller
work. Source admission sets a transaction-local canonical namespace before
current execution/user/app queries. The same existing authentication code is
shared with extraction commands; read permission alone is not mutation authority.
The [shared Source Session contract](SOURCE_EXTRACTION.md#transaction-and-storage-ownership)
requires standard public `Session.get_bind`, including inherited subclasses and
explicit bindings to the same Engine. Selectively routed TextClause helpers are
refused before any SQL; validation does not acquire rejected caller ownership.

## Changes and ordering

The Stage takes the standalone Source gate, the fixed partition capability's
descriptor SHARE, a narrow File UPDATE lock and its Source projection stream.
It reloads actual current scope/state/tip after waits, sets `deleted_at` and purges
canonical searchable artifacts without fetching the old text/blocks/metadata.
It appends the retained DELETE event in the same Source transaction and rechecks
actual Source writer admission and current execution/user/app/scope after the
event UUID lock wait. Lock/statement timeouts are the existing5s/15s Source policy.

The intent has a fixed protocol/command, spec/before digests, original execution
correlation and genuine predecessor event/digest/revision. Raw storage key,
filename and artifact bodies are not copied into the event. PostgreSQL supplies
the actual immutable producer identity. Core receipt/head/job tables, physical
storage, providers, cleanup jobs and Core ingress are untouched.

## Provisional result and same-ID observation

The Stage receipt is always `provisional=True`. The caller must retain the
original spec/event and handle its own COMMIT ACK or uncertainty; this module
does not commit, retry, regenerate an event UUID or provide a durable caller store.
Body `BaseException` propagates to the caller; this Stage has no automatic
cancellation rollback or typed COMMIT-unknown runner. The caller must handle
rollback/close and discard its owned Session on every interrupted path, preserving
the original outcome even if cleanup fails. Existing extraction runner cleanup
proofs do not establish an additional cancellation guarantee for this API.
After an uncertain COMMIT, use
`observe_native_root_file_soft_delete(db, *, spec, expected_event_digest,
current_execution_ref)` with the original spec and a current execution for the
same actor. The event digest is the fixed DELETE intent's digest, not the spec
digest or predecessor digest.

Observation uses a separate fresh current-authorized Source Session and reads the
exact immutable event and predecessor. A returned receipt is historical event
evidence (`historical=True`), not a new mutation or proof that the current File
still has its old tombstone after a later genuine tip. An absent event returns
`None`; absence does not prove rollback or permit mutation replay. Current scope,
owner, app, execution and producer admission still apply even for history.
Observation acquires its current read locks/admission but performs no Source DML.

The trusted caller's File+event writes are one transaction. This Stage does not
add a SQL terminal seal preventing arbitrary later caller writes before COMMIT,
nor prove physical object deletion. Publication/apply's top-XID seals and durable
active holds remain separate essential contracts.

## Integration limits

Legacy whole-tree deletion's exclusive descriptor lock interoperates with this
capability's SHARE for this existing leaf. The new Source advisory gate alone
does not serialize all legacy participants. Full tree adoption/drain, bounded
descendant handling, publication holds across all native/managed mutations,
company audit, exact-version read/cleanup, managed logical identity and service
activation remain required. This API is a core-owned server primitive, not an
independent app's database extension; independent apps use public platform APIs.
