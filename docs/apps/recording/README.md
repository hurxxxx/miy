# Recording App

Recording is a personal app. It owns recording upload, transcription and summary state, durable
results, linked targets, playback authorization, and explicit publication of a completed result.
App entry and availability follow the [App Platform Contract](../../domains/app-platform/README.md).

## Result And Worker Contract

- Collection responses contain status and small metadata, not transcript or summary bodies. The
  recording detail response owns the current `RecordingResult` and publication list.
- One durable result per recording stores transcript, summary, verifier note, and a monotone version.
- Each processing run has an attempt ID. Transcription fences provider and persistence work by the
  current attempt, then creates or increments the transcript result version.
- Analysis snapshots that version before its model call and rechecks it under the current attempt
  before saving. Verification and final persistence carry and recheck both attempt and version.
- Stale attempt/version work exits without changing current state. An exact replay of an already
  completed final payload returns idempotent success rather than reporting supersession.
- Workers recheck Recording app availability after claim and before provider or storage mutation.

## Legacy Queue Submission And Retry

The default API still submits the existing four-stage Celery chain. The final
task ID remains the Recording attempt ID; no managed-command protocol or new
worker profile is selected automatically.

An exception after attempting publication cannot prove that the broker rejected
the chain. The API retains the committed attempt, saved audio and any concurrent
worker progress, and returns localized HTTP 500 `recording.processing_submission_unknown`.
It does not mark processing failed, revoke/clear the attempt or submit again.
A processing-state COMMIT exception similarly returns
`recording.processing_update_unknown` after best-effort rollback, without another
publication or failure write. An acknowledgement may have been lost after commit;
rollback does not prove that the saved state or accepted broker work disappeared.
The stored audio/source is not deleted because this request returned an error.

Both Recording and Meeting retry APIs acquire the source writer fence, reload
the Recording under a row lock, and recheck current app/resource authority.
Broker preflight occurs before that admission. Retry resets and the new attempt
are saved in one transaction, and publication follows only its acknowledged
commit. A denied current scope cannot leave a half-reset pending source without
an attempt; prior result fields remain intact on rollback.
An existing attempt, including pending or failed-looking state, returns 409 and
is not replaced. Explicit retries remain available after a known terminal failure
has cleared the attempt, or a queue preflight failed before publication was
attempted. Completed processing retains its existing retry refusal.

Legacy pending state does not distinguish confirmed queue acceptance from an
unknown send. A stranded attempt therefore requires explicit reconciliation;
elapsed time, failed revoke or absent worker inspection is not evidence permitting
a replacement. This change does not add broker receipts, remote cancellation,
exactly-once execution, a background repair loop or automatic retry. The proposed
managed delivery protocol and split worker activation remain separate work.

## Docs Publication

- Processing never creates a Docs document automatically.
- `POST /api/v1/recording/recordings/{recording_id}/publications/docs` is an explicit user action.
- Publication requires recording access, a completed non-empty summary, current Recording and Docs
  app availability, and current Docs write authorization.
- The publication key is `(recording_id, target_app, result_version)`. Repeating publication for the
  same result version returns the existing source-linked document instead of creating a duplicate.
- A newer result version does not rewrite an older publication. The detail response exposes each
  publication and its result version.

## Checks

```bash
(cd apps/api && uv run --python 3.12 --group dev python -m pytest tests/test_recording_targets.py tests/test_meeting_recordings.py -q)
(cd apps/worker && uv run --python 3.12 --group dev python -m pytest tests/test_app_execution_policy_workers.py -q)
pnpm exec vitest run --root apps/web src/app-modules/recording/views/recording-collection-workflow.spec.tsx src/app-modules/recording/views/useRecordingDetailController.spec.ts
```
