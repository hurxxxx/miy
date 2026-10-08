# Files content compatibility before runtime replacement

`cutover_gate.py` owns the read-only `files-result-stamp-v1` check. The ordinary
Files keyword and vector serving rules continue to require the candidate's
original raw SHA, partition and UTC microsecond `extracted_at` marker. An older
index without that marker requires explicit rebuilding; serving never supplies
the current marker to an old candidate.

The executable entrypoint is:

```sh
apps/api/.venv/bin/python -m miy_api.domains.files.cutover_gate
```

It accepts no arguments, completion flag, generation override or fallback. A
successful receipt means that this invocation completed its current check. It
does not authorize a deployment, prove writer quiescence, or stay current after
writers resume. The fixed version identifies this check's contract, not a
schema-version checkbox that can certify an index without reading it.

The typed `rag_enabled && files_retrieval_enabled` predicate controls checking.
An inactive configuration returns `result=inactive` before opening a Source
session or constructing a backend, materializer or runner. With the predicate
active, a count of the actual whole Source File table equal to zero returns
`result=empty_source` before those constructors. Pending, failed, unsupported
and deleted rows do not count as an empty Source table merely because the
derived snapshot contains no ready resources.

An undeleted ready Source File without `extracted_at` refuses before any backend
construction. For an active nonempty Source, the gate calls the existing
`FilesGenerationRunner.verify_active()` directly. That verifier requires the
registered active pair, exact physical names/configuration and alias targets,
complete current Source and physical resource/record counts and identities,
stable keyword/vector projection digests including `metadata.extracted_at`,
stored release evidence, current model configuration and drained projection
queues. Its gate-only materializer opts into the existing empty-resource
reconciliation flag, so nonempty deleted/unsupported-only Source still requires
drained jobs. A passing index-presence check alone is insufficient. Source stamp
absence, an older unstamped envelope, incomplete inventory or stale release
evidence cannot produce `result=verified`.

The CLI supplies read-only Source transactions with five-second statement and
lock timeouts. Cached evidence may be chunked and hashed locally. Verification
never calls materialization, object reads, parsing/OCR, embedding, reindexing,
alias changes, broker publication or schema/role mutation. The composition's
embedding and materialization factories raise a fixed refusal if unexpectedly
invoked. The existing physical inspectors read complete payloads to compute
digests; none of that body, endpoint, key, cohort or provider exception is
printed. Output contains only the fixed status, gate version, result mode or
allowlisted refusal reason.

The owned Linux CLI uses a cooperative process signal deadline of 120 seconds,
followed by at most five seconds for owned backend cleanup. Cleanup cancellation
or failure preserves an already completed verification or the original fixed
refusal. The production entrypoint additionally runs the owned container process
under `/usr/bin/timeout --signal=TERM --kill-after=5 130`; this bounds a blocked
native call beyond Python's cooperative signal delivery. A killed or timed-out
process cannot acknowledge compatibility and prevents candidate startup. Neither
mechanism claims to cancel a remote server operation; this gate only reads.

`scripts/prod-app.sh deploy` and `up` use the same forward sequence:

1. Stop the existing `api`, `worker` and `beat` writer services successfully.
2. Apply the candidate migrations.
3. Run the owned compatibility gate against the candidate image and existing
   current Source/physical indexes.
4. Start the candidate runtime, then run its smoke check.

Candidate validation first checks `/usr/bin/timeout` is executable inside the
immutable image using a network-disabled container. Direct `up` checks its
captured immutable current image before stopping writers too. A missing required
executable fails before current services are touched.

The stopped-writer span continues through checking and replacement. Other
operator-owned writers must also remain quiesced; this check does not fence
arbitrary independent producers. This sequence introduces no Source ownership
transition, new grants or activation of the prepared internal protocols.

Any failed forward step prevents candidate startup or reports failed startup.
`deploy` uses the existing immutable previous-runtime restoration and smoke
contract. Its old definitions are restored without invoking the new gate.
`up` captures its exact current image identity before stopping services and
restores that same image only if the current tag still resolves to that identity;
`prod-previous` can be unrelated and is never its recovery target. Failed
restoration is reported separately, and even a successful restoration keeps the
original forward operation failed. Existing rollback definitions and their
schema-compatibility requirements are unchanged.

Repair remains an explicit operator action through the existing
`apps/api/scripts/manage_files_retrieval_generation.py` generation preparation,
materialization/replay, validation and cutover contract, with its required
quiescence and quality evidence. This gate does not automate paid repair, invent
a Source result stamp, or certify legacy prepared-path adoption. After an actual
rebuild, run the same read-only verification before resuming the new runtime.
