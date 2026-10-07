# Worker App

Celery background worker.

The existing `miy_worker.celery_app:celery_app` is the **only active legacy
composition**. Its 28 public task IDs, nine Beat entries, payloads, explicit
queue routing, retry/lease/generation and app admission behavior remain unchanged.
`miy_api.core.worker_queue_contract` owns the exact task/module profile inventory
and queue plans; `miy_worker.task_catalog` owns schedule intervals and projects
that inventory into the Celery bootstrap.

## Split profile artifacts

| Entry | Actual registry | Execution state |
| --- | --- | --- |
| `miy_worker.celery_app:celery_app` | All 12 modules / 28 tasks / 9 Beat entries | Existing legacy behavior |
| `miy_worker.platform_app:celery_app` | 8 platform modules / 14 tasks / 6 Beat entries | Inactive; execution refused |
| `miy_official_worker.celery_app:celery_app` | 4 official modules / 14 tasks / 3 Beat entries | Inactive; execution refused |

The separate [official entry wheel](../official-suite/worker/README.md) reuses
actual task implementations in the matching worker wheel. Platform and official
plans route to `miy.platform.<legacy-queue>` and
`miy.official.<legacy-queue>` respectively. Neither subscribes to legacy queues.
The legacy route registry and callers' explicit queues are unchanged. Split
namespaces are future route contracts, not evidence of broker ACLs or activation.

Python caches modules and Celery can share task decorators across apps. The
small `task_binding` adapter selects exactly one profile/app per process and
rejects a different profile or unowned module. Split decorators remain local to
that app and refuse task execution. Celery still owns registration, signatures,
scheduling and worker lifecycle; there is no second execution engine. Installed
artifacts prefer their matching API wheel; source checkout fallback remains for
the legacy development environment.

Both split entries reject Worker/Beat construction, broker connection,
publication and direct/eager business task execution with
`worker_profile_not_activated`. No CLI flag, queue name, environment setting or
caller-provided identity opens them. Inactive import does not read runtime
credentials, initialize DB/platform extensions or attach the legacy Beat health
hook. The Mail decorator uses its existing typed lease default for inspection;
this does not replace configured lease values in the active legacy worker.

The common fail-fast producer accepts an explicit `profile` argument but rejects
both inactive profiles **before** constructing Celery. Omitting it keeps legacy
behavior, including caller-selected queues, task IDs and args/kwargs. The pure
`worker_profile_publication_route(profile, task_name)` rejects unowned tasks but
only describes intended routing; it does not publish or authorize a request.
Existing API and self-republishing worker call sites still use legacy settings.
They have not silently switched to these new route plans.

[Local wheel inspection](../../ops/official-suite-worker/README.md) verifies real
module registration from matching packaged inputs without starting a service.
Building or importing an inactive entry is not a completed service cutover.

## Required activation connections

These remain structural work under the [official cutover owner](../../platform-redesign/OFFICIAL_API_CUTOVER.md),
not optional app feature work:

- **Core producer and outbox owner:** bind each durable publication to a current
  enabled worker profile and immutable artifact/generation before selecting its
  fixed queue. Preserve existing task IDs/payloads and publication deduplication.
  A future versioned AMQP execution envelope needs the profile, suite generation,
  artifact digest and existing job/attempt identity; caller-supplied headers alone
  must never be trusted. No such new wire envelope is emitted by this slice.
- **Core writer/DB role owner:** authenticate the deployed service principal and
  current `official.suite` generation, admission and original resource ACL. Check
  after claim and before source mutations; never discover and adopt a newer
  generation. Data's transaction source locks cover only their open transaction.
- **Beat owner:** maintain one authoritative renewable schedule-owner lease with
  an epoch/fencing token per active profile, rechecked before each publish and
  across failover. The local Beat health timestamp is liveness, not that lease.
  Until this exists, do not start split Beat or run two schedulers for the same
  entries; old queued publications need an explicit drain/reconciliation policy.
- **Task/effect owner:** retain Recording attempt IDs, Mail processing leases and
  Files cleanup claim/idempotency rules while binding them to deployment identity.
  Claim commits release DB locks; later provider/object effects need their own
  admission and completion/compensation boundary. A source trigger alone cannot
  stop already accepted external work. Reconcile unknown outcomes without blind
  re-execution or destructive cleanup.
- **Release/routing owner:** provision least-privilege broker queue/exchange ACLs
  and service DB credentials, drain the previous consumer/publisher, verify the
  artifact and exact CAS transition, and preserve rollback with monotonically
  newer identity. No broad `celery` subscription or auto-created missing queues.

No operational profile, queue, Beat lease, role, worker service or production
release is created or activated by these source changes.

## Files cleanup transaction fence

The legacy Files cleanup task now participates in the existing official source
fence. Its durable claim still commits before storage access. The claim captures
the job/key/attempt/exact five-minute lease deadline before that commit, then the
same Session starts another transaction and reacquires the source SHARE lock.
It locks and reloads the exact pending job and refuses a changed or already
expired claim before deleting. No separate outer connection or whole-task
transaction is used. The source and job locks stay held through deletion and
its final success/retry/failure commit. A lease expiring during the admitted,
locked call does not discard that attempt's outcome.

If a claim or final COMMIT acknowledgement is lost, this invocation starts no
new deletion or failure/retry transaction. The database may contain either the
durable lease or an already completed result. Existing due-lease recovery and
idempotent missing-object handling remain; no new uncertain-outcome retry engine
is added. This is not proof that a remote deletion stopped when a process or
connection disappeared.

The actual Celery task options are `time_limit=120` and `soft_time_limit=90`.
The former `task_time_limit` decorator keywords were configuration-setting names
and did not set these task execution deadlines. The [Celery task contract](https://docs.celeryq.dev/en/stable/userguide/tasks.html#Task.time_limit)
distinguishes task deadlines from I/O timeouts. Hard termination can release a
database lock while a remote server still completes an accepted request; it
does not establish that deletion failed or authorize destructive compensation.
No new transport retry policy or operational worker is enabled here.

This closes the Files worker's admitted delete transaction, not all official
worker effects. Mail's publication claims and after-commit publisher,
Recording/Meeting's accepted remote-work lifetimes, Meeting's committing ASR
progress callbacks and post-commit spool cleanup, producer/chain retries, projection outboxes
and the Beat owner lease remain explicit structural work. The Files correction
did not change their task deadlines or external-effect lifetimes. Mail's separate
subsequent phase work and Recording's source handoffs are described below.
Existing source ACL and app admission
remain required.

## Files prepared Core cached projections

The internal typed prepared Files composition reads a committed ready Source
artifact under an actual Core event/current-head witness. It uses the existing
adapter and worker task without storage reads, parsing/OCR or Source callbacks
that mutate extraction fields or emit intents. The
[Files projection owner](../api/src/miy_api/domains/files/CORE_PROJECTION.md)
defines reader bounds, exact event/checksum validation and the limited fresh
read-only role. That reader role is not the complete Core job writer profile.

Prepared preflight runs before provider construction. Pending, failed,
unsupported, malformed or checksum-conflicting artifacts are held in the existing
`FAILED` status, with the same job/event IDs and a refunded claim attempt. An
explicit DELETE must match an actual deleted event. Actual missing/deleted Source
under an UPSERT remains a derived-only delete. Later control errors may follow an
effect and retain the attempt as `file_projection_effect_unknown`; the worker
does not invoke a Source failure callback or automatic provider/task retry.

A private typed hold-COMMIT control returns
`file_projection_hold_commit_unknown` if saving/observing the hold is uncertain.
It bypasses the generic failure handler and does not reset work to pending. Only
an observed `FAILED` row is unclaimable by Beat: an uncommitted hold can leave the
original processing claim discoverable by legacy expired-claim recovery. Same-ID
observation, durable effect admission and authoritative Beat ownership remain
operational gates; this catch does not stop a live scheduler.

Prepared ready callbacks stage fenced Core keyword work with immediate publication
disabled for new and merged jobs. Persisted pending rows are still discoverable
by a future scheduler. No profile, worker, Beat entry, broker or provider is
activated. Ordinary legacy composition is preserved. Source-owned extraction
requests/results, genuine pending/ready ingress, immutable input and full Files
service/worker role composition remain mandatory cutover work.

## Mail synchronization phase fence

The durable Mail processing claim now copies its job/account/mailbox/operation,
attempt number, lease owner and exact deadline before COMMIT. The same Session
retains the existing commits for claim, account status, mailbox discovery/state,
batch/cursors and final result. Each subsequent phase reacquires the existing
official source SHARE and the exact processing job row, then rechecks current
account-owner/app authority before synthetic or real provider I/O. The locks
remain until that phase commits or rolls back. No outer pool connection, new
model, queue payload or whole-task transaction was added.

A new provider call requires the original unexpired claim. An already admitted
call can finish after its deadline while holding the row lock; another worker
cannot steal that row then. If another mailbox would start after expiry, the
existing batch transaction rolls back and no new call starts. Success, failure
and cancellation must still match the original processing claim. A stale task
returns `lost_lease` without changing a replacement attempt. Current ACL
revocation discards the response and cancels only the exact job; previously
committed account/status metadata is not a new success assertion. Legacy direct
`mail.sync_account` still has no durable job claim, but each existing phase now
checks account authority and the same source fence.

Writer refusal and database/control failures do not become provider errors or
schedule another retry. Any raised phase COMMIT is conservatively reported as
`mail_sync_commit_unknown`, even when rollback also fails. This invocation
performs no further provider call, result/failure write or Celery self-retry.
The database may already contain that phase's result; existing durable lease
recovery remains and is not a guarantee of exactly-once provider access. Known
provider failures still use the existing attempt limit and backoff after exact
claim/current authority checks.

The two actual Mail task options use `time_limit` and `soft_time_limit`, deriving
their existing configured values from `MIY_MAIL_SYNC_PROCESSING_LEASE_SECONDS`
(defaults 900/840 seconds). The old `task_time_limit` decorator keywords did not
set a Task execution deadline. These limits require a supporting worker pool;
termination does not prove a remote accepted call stopped. Broker publication,
the due dispatcher and after-commit publication hook, trusted profile/generation
envelopes and Beat ownership still need their separate structural implementation.
No split worker profile or runtime identity is activated by this phase fence.

## Recording summary and verification phase fence

`recording.analyze_transcript` and `recording.verify_transcript_summary` now
capture the original recording, attempt, owner and result version. Verification
also requires the exact supplied summary. On the same Session, each phase takes
the existing official source SHARE lock, then locks/reloads that recording and
result and checks current owner/app authority. Analysis keeps its existing
heartbeat COMMIT and reacquires these locks against the original claim afterward.
The source and row locks remain through the registered gateway call and phase
result COMMIT. A result or attempt replaced before admission is never adopted.

The real common gateway, Hermes workload staging/dispatch, validated result
callback and authoritative audit remain in use. They already open additional
Sessions: owned PostgreSQL checks exercised the full path with three available
connections. A one-connection pool is insufficient and fails at its bounded
checkout timeout without provider admission, phase failure writes or self-retry;
audit persistence cannot be promised when that pool cannot acquire a connection.
The worker adds no outer fencing connection and does not bypass these owners.

Current ACL is checked again after the gateway. Revocation and known provider
failure can finalize only the same original attempt/version. Known provider
errors retain the existing attempt limit/backoff. Writer refusal, stale claims,
SQLAlchemy errors (including those directly wrapped by the gateway) and a raised
phase COMMIT do not trigger another failure transaction or self-retry. A phase
COMMIT exception becomes `recording_summary_commit_unknown`; best-effort rollback
does not imply the server rejected that commit. Previously committed heartbeat,
Hermes or audit rows are not rolled back with the source result.

These two task options now use the supported `time_limit` names, preserving the
previously intended 900/600 seconds and adding no soft deadline. A supporting
Celery pool is still required. Process termination or loss of the source lock
does not prove that an accepted native run stopped. Hermes has its own durable
run/stop recovery; this change does not merge that lifecycle into the recording
attempt. The subsequent ASR/source finalization handoff is described below.
Remote accepted-work recovery, chain/broker publication, Beat ownership and
trusted split-worker activation remain separate structural work. No operational
profile or service is enabled.

## Recording ASR progress and final persistence

Transcription freezes the original attempt, owner, saved audio key and transcript
result version (including no result yet). Its existing Session takes source
SHARE, parent/result row locks and current owner/app authority before health,
download and ASR work. Initial and increasing progress still commit durably.
Immediately after each such COMMIT the same Session reacquires these checks
before proceeding or returning from the ASR callback. Repeated or lower progress
also checks current authority. A replacement attempt, file or result is not
adopted, and an admitted provider result cannot overwrite it.

ASR callbacks must run synchronously on the initiating thread and propagate
exceptions before the backend continues or returns. The SQLAlchemy Session is
not thread safe; asynchronous callbacks or swallowed failures violate the backend
contract. Built-in HTTP adapters call progress before POST and after the full
response; local adapters call at synchronous computation/segment boundaries.
Drain waits during the live synchronous request/segment. At a progress COMMIT,
drain can win the handoff, in which case reacquisition fails and prevents the
next caller-controlled step. This is not one atomic ASR transaction or proof that
all underlying native computation has stopped.

Transcript and final persistence outcomes recheck the exact claim/version before
writing or failing it. Already completed persistence returns read-only after
current actor/app validation, including while the source is draining; it does
not resurrect a cleared attempt. DB-only persistence no longer turns arbitrary
exceptions into broker retries. Source/SQLAlchemy failures are control failures.
Any raised ASR progress, result or failure COMMIT becomes
`recording_phase_commit_unknown` after best-effort rollback, with no further
failure write or self-retry in that invocation. The database may already contain
that progress or outcome. Known provider failures keep the original retry limit
and backoff only after the original source claim and current ACL are rechecked.

The actual task options are transcribe `time_limit=3600`,
`soft_time_limit=3300`, and persistence `time_limit=300`, preserving the intended
values. Pool support is still required. These source phases need no extra outer
connection; the owned PostgreSQL checks use one available worker connection.
This differs from the summary gateway's existing additional audit/runtime
Sessions described above.

An accepted remote ASR request can continue after transport timeout, worker loss
or process termination. The existing ASR `TransientError` contract can still
retry an ambiguous remote acceptance; there is no durable remote request ID or
cancellation receipt here. Safe remote reconciliation, API attempt-COMMIT to
broker publication, Celery chain/self-retry publication and Beat ownership remain
required independent work. No exactly-once execution, remote cancellation or
split-profile activation is established by the progress handoff.

Tasks:

- AI graph dispatch/execution
- document/RAG sync and search indexing
- OCR/document extraction
- meeting/recording processing
- mail sync
- media and orphaned-storage cleanup

Run:

```bash
./dev.sh --with-worker
```

Use root `.env.example` plus ignored `.env`. Do not commit secrets or operations data.

Beat's production health check measures recent successful task publication, independently of
worker ping and API health. See the [runtime contract](../../docs/domains/release/README.md#production-app-contract).

Executable app-owned user work rechecks runtime availability after claim and before provider or
app-data mutation. Compensating cleanup may continue after disablement when its only effect is
removing orphaned/expired storage; it must not publish new user-visible app state. The
[App Platform Contract](../../docs/domains/app-platform/README.md) owns the shared rule, the
[AI Execution Contract](../../docs/domains/ai/execution.md) owns graph claims/checkpoints, and the
[Recording App](../../docs/apps/recording/README.md) owns recording attempt/version fencing.

User jobs retain the initiating user in their LLM execution context and recheck current company
app admission. Meeting publication also checks the uploader's current meeting participation,
Docs admission, and PMS task write permission before writing linked results. System search/RAG
projection jobs check company master switches and projection versions; query-time source ACL
still determines who can read indexed content. Regression coverage is in
[company worker security tests](tests/test_company_worker_security.py).
