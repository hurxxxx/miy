# Prepared Qdrant materialization

`prepared_qdrant.py` owns the inactive, explicitly composed Core adapter for an
already prepared physical vector collection. Ordinary `QdrantVectorIndexClient`
and its defaults are unchanged. No default factory, provider, task, queue, service
or generation is activated by this module.

The adapter preserves existing Rag materialization method signatures and reuses
the owned partition/resource filters, collection schema checks and canonical
point/payload rules. `ensure_collection` validates an existing collection and its
schema/indexes; it never creates a collection or payload index. Compatibility,
physical target ownership, current Source/Core event admission and lifecycle
fencing belong to their existing Core preparation/execution owners.

`prepared_qdrant_client` owns one REST SDK client and transport for one bound
collection. It disables gRPC, automatic retries, redirects, environment proxy
routing and the SDK's background compatibility request. Explicit target
preparation still owns compatibility validation. Query, health discovery and
collection deletion are outside this materialization scope and refuse without
requests. Rebinding can return only the same collection. Close preserves the
original controlled outcome or acknowledged result, including cleanup
cancellation; it cannot grant another execution permit.

The trusted endpoint must be HTTP(S) with a hostname and root path. Userinfo,
query/fragment, controls/whitespace and path prefixes refuse before SDK or
transport construction. This profile does not support a URL prefix. Credentials
come from the separate existing typed Core composition, never a URL. ContextVar
filters suppress only this operation's HTTPX/httpcore I/O logs, including response
headers at DEBUG; unrelated clients and application logging remain active.

The trusted frozen policy may only lower positive finite defaults: elapsed120s,
phase5s, page128, pages64, scanned points8192, retained delete IDs8192, response4MiB,
requests96 and aggregate response64MiB. Integers require exact integer types;
durations require exact finite int/float types. Bool, coercion, NaN, infinity,
zero/negative values and raised limits refuse before SDK construction. The
budget starts before construction and never resets between methods or pages.

The public HTTPX transport clamps the final SDK-built request's connect/read/
write/pool timeout fields. It counts all requests and response bytes, including
existence/schema/error responses. A public response-stream wrapper checks the
per-response and aggregate limits before SDK JSON/model parsing. Identity
encoding is requested; compressed responses refuse before decoding. Errors carry
only stable bounded control identifiers, without provider text, URLs or bodies.

Both stale-tail cleanup and whole-resource deletion perform a bounded complete
ID scan using the exact existing partition/resource filter. Whole delete never
uses a count-then-filter mutation. Oversized pages, point/ID/page limits,
duplicate IDs, invalid or cyclic offsets and elapsed budget exhaustion refuse
before the final delete. After terminal pagination, at most8192 explicit IDs are
submitted in one delete. Empty IDs cause no mutation. The stale selector preserves
legacy integer/digit-string chunk index semantics and requests only that payload
field. No numeric-range shortcut, partial-cleanup success or second Rag pre-write
callback is used. Upsert and delete require `wait=True` and exact SDK `completed`
status; acknowledged/wait-timeout/malformed results remain uncertain.

An adapter refusal after prior keyword/vector effects does not undo those effects.
The [prepared Core effect owner](../../retrieval/FILE_EFFECT_EXECUTION.md) retains
the original operation/event/generation and armed history, with no automatic
retry or cursor progress. This adapter supplies no identity, app admission or
resource ACL authority and does not establish cross-store atomicity.

Synchronous phase timeouts and elapsed checks **are not a hard total cancellation
deadline**. DNS, slow headers, one blocked operation and synchronous CPU/cleanup
may delay the next owned check. A thread/future timeout does not cancel the remote
call. F5 still owns hard cancellation, registered embedding/gateway batch budgets,
output dimensions/request allocation, complete factory/audit/target integration
and legacy-writer quiescence. Count/scan caps do not prove complete cleanup of a
larger physical resource: that operation stays held for explicit reconciliation.

Focused tests use the pinned public Qdrant SDK with synthetic HTTPX transports
and clocks, then owned bounded loopback TCP for actual phase timeout, byte cap,
redirect and retry behavior. They call no live/shared provider or infrastructure.
They do not prove hard cancellation or operational readiness.
