# Prepared Files effect execution

`prepared_file_effects.py` and `prepared_file_materializer.py` own the inactive
Core execution composition. The database header, privileges, fixed capability,
triggers and retirement rules have one owner:
[FILE_EFFECT.md](../official_apps/FILE_EFFECT.md). Strict cached content belongs
to [CORE_PROJECTION.md](../files/CORE_PROJECTION.md). This composition does not
register a worker, enable a queue, deploy a service or invoke a live provider.

## Retained identities and owned sessions

The trusted caller retains a `FileMaterializationEffectSpec` before arming. It
contains the operation UUID, complete actual Core event, exact persisted pair
UUID/key/physical/schema identities and positive partition metadata version.
The batch adapter requires a caller-owned `retain_operation_id` callback; it
does not invent replacement IDs after uncertainty. The caller must preserve its
workset/IDs across process loss. Existing history is found by the event/pair
tuple and then compared against its full retained spec.

The callback is a trusted retention contract; this module does not implement a
durable caller checkpoint. If arm COMMIT loses its ACK before a row becomes
observable, PostgreSQL history alone cannot retain that caller's unknown state.
The caller must preserve the original UUID/unknown and refuse automatic re-entry
or a replacement UUID even when observation returns absence. Durable external
retention belongs to the required runtime composition.

Every discovery, history, arm, effect and reconciliation session comes from an
explicit factory. Before SQL or cleanup, the validator rejects an active/nested
transaction, pending ORM work, a Connection bind, or a different mapper/table
Engine among the fixed query models. Only then does it own rollback/close. The
actual safe Core LOGIN, Source-principal exclusion, READ COMMITTED/nonautocommit
and local canonical lookup namespace are checked before any content/control
query, including an empty batch. Local lock and statement limits are 5s/15s;
they are not a deadline for remote computation.

## Durable arm, live permit and history

`PreparedFileEffectRunner.arm` checks exact existing history without requiring
the historical Source/head to remain current. Existing armed/complete records
return receipts only. A new arm obtains the fixed lifecycle capability before
operation DML, loads one strict paired Source snapshot and stores its actual
Source witness/result stamp. SQL returns the real immutable header digest;
Python does not manufacture an equivalent JSON hash.

Only an acknowledged arm COMMIT creates the original live permit. It cannot be
serialized or consumed twice. Arm COMMIT uncertainty retains the same spec and
actual digest and returns no permit. `observe` reads those exact identities and
may report absence, armed or complete. None of these observations reconstructs
a permit or grants a retry. Missing history is not proof of rollback.

Effect execution consumes the permit, opens another fresh owned session,
reacquires the capability before operation locks, and compares the immutable
receipt. A refusal before the effect callback is known zero provider/compute
attempts and retains the armed receipt in `FileMaterializationPreflightRefused`.
The permit remains consumed. Once the callback begins, construction, embedding,
mutation, cancellation, cleanup or COMMIT failures retain the same operation as
`FileMaterializationEffectUnknown`. Cleanup cannot replace that control, clear
the record or authorize automatic re-embedding.

The owned session's final rollback/close also isolates `BaseException`, including
cleanup cancellation. It preserves the body's retained refusal/unknown receipt
and a known arm or completion COMMIT ACK; cleanup alone cannot downgrade an
acknowledged outcome. Cancellation during the body or COMMIT remains classified
by the runner while it owns the operation receipt.

## Backend ACKs and atomic progress

Both projections come from the admitted bounded Source snapshot. The existing
public RAG `sync_projection_with_fence` performs embedding first. Its exactly
once callback rechecks lifecycle/current Source/Core/output and writes keyword
before vector mutation. Missing/repeated callbacks refuse; upsert/delete accept
only the exact strings `upserted`/`deleted`. `unchanged` is insufficient because
OpenSearch external-version equality does not attest body/result-stamp equality.
The returned vector operation/collection and upsert chunk count must match.

The entire RAG return, including trailing stale-chunk cleanup, and keyword
refresh ACK precede completion. Genuine deletion explicitly repeats the fence
before both delete calls. There is no intermediate COMMIT. Final fences, exact
legacy job resolution and armed→complete share one Core COMMIT. The job resolver
uses fixed predicates/five update fields and does not hydrate payloads, traces
or private error columns. Older fenced active jobs are cancelled; exact current
event/version/partition/state/operation jobs succeed; inconsistent jobs remain
visible. A final COMMIT uncertainty is observed under the original digest.

The batch/cursor algorithm remains in `FilesCachedProjectionMaterializer`; three
protected hooks supply session admission, per-event execution and outstanding
counts. The prepared adapter holds reconciliation for **any** armed Files
operation, including absent/FAILED jobs, superseded heads and zero Source
inventory. This is an explicit conservative global hold because the existing
observer has no target argument. No mutable last-spec weakens it. The runner's
optional `requires_empty_reconciliation` contract makes this check apply to
empty prepared generations while retaining legacy behavior.

## Remaining structural gates

Explicit factories must later be composed with current product gateway/identity,
audit, owned physical targets and total remote budgets. The separate
[prepared Qdrant adapter](../rag/providers/PREPARED_QDRANT.md) provides finite
request/response/page/point limits, exact update ACKs and a shared elapsed budget
without changing the ordinary provider. This module installs no such factory.
Its synchronous phase timers are not a hard cancellation deadline; complete
embedding/keyword/factory/cleanup and durable caller retention remain runtime
composition gates. The inactive composition does not attest live routing,
backend adoption/idempotency or cross-store atomicity. No runtime is activated
until those contracts are closed. Arbitrary legacy Source edits still require
quiescence; cooperative Source locks do not cover writes without genuine intent.

Controlled behavior evidence, restricted PostgreSQL authority/concurrency and
independent review are recorded separately in the root
[redesign validation](../../../../../../platform-redesign/VALIDATION.md). Source
publication, full bootstrap/tree coverage and service/worker/Beat cutover remain
required structural work, not deferred individual app feature issues.
