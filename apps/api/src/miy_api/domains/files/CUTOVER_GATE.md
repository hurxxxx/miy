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

1. Stop the existing `api`, `worker` and `beat` writer services successfully,
   retaining their Compose grace periods (45 seconds, 65 minutes, 45 seconds).
   No shared stop timeout shortens the worker graceful-shutdown contract.
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
contract. Its explicit pinned-bundle path restores old definitions without invoking the
new gate; the compatible tag-only recovery path retains its existing current
definition/schema compatibility requirement.
`up` first inspects the actual `api`, `worker` and `beat` containers.
It validates their IDs, immutable images, exact Compose project/service
identities and existing configuration-hash labels. All three images must match
the selected current image. A successful state inspection must report a known
Docker status (`created`, `running`, `paused`, `restarting`, `exited` or `dead`),
a Boolean running value and a known health value (`healthy`, `starting` or
`unhealthy`), or absent `State.Health` from a not-yet-started container.
An absent health value provides no healthy recovery evidence. A container being
removed refuses. Known stopped, starting or
unhealthy containers may proceed through the forward stop, migration, gate and
startup sequence. Only three previously `running|true|healthy` containers are
captured as an automatic recovery target. Inspection failure, empty/invalid
status, invalid running/health values, partial, mixed, retagged or malformed identities refuse before stopping
writers. With no existing containers, first
startup may proceed only through the forward gate and has no automatic recovery
target. Current Compose `config --hash` output is not equated with live labels:
the public CLI and container creation resolve `env_file` differently.

A failed pre-start step can restart only those attested previously healthy containers,
after rechecking their original IDs, captured definition labels and the current
image. The existing Docker container retains its original configuration and
environment; changes to current Compose files do not change that recovery
definition. Recovery
uses public `docker start` with only the captured container IDs, waits up to
600 seconds for those unchanged containers to become healthy, then runs the
existing bounded smoke check;
it never force-recreates a gate-refused candidate. Lost/replaced containers, tag
or captured-label drift, and failures after the full runtime startup attempt require
explicit operator/pinned-bundle recovery. The latter may have changed other
services, so three writer identities cannot prove a complete old runtime.
`prod-previous` is never an inferred `up` recovery target. Failed restoration is
reported separately, and successful recovery still leaves the original forward
operation failed. A known stopped, starting or unhealthy prior runtime has no
automatic restoration path after a refused gate; it cannot start through recovery.
Existing explicit rollback definitions and their
schema-compatibility requirements are unchanged.

Repair remains an explicit operator action through the existing
`apps/api/scripts/manage_files_retrieval_generation.py` generation preparation,
materialization/replay, validation and cutover contract, with its required
quiescence and quality evidence. This gate does not automate paid repair, invent
a Source result stamp, or certify legacy prepared-path adoption. After an actual
rebuild, run the same read-only verification before resuming the new runtime.
