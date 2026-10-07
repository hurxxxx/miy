# Selected-file source access

Files owns candidate discovery, resource ACL evaluation, selected metadata/version and object reads for the independent app picker. The [Core selected-file contract](../independent_apps/README.md#selected-platform-files) owns signed requests, current app/source-session authority and the routes. This adapter does not expand existing `/content` grants, expose object locations, create persistent copies or add a parallel Files permission system.

## Current source checks

`access_policy.py` factors the existing browse policy for reuse. Native Files records require owner or company visibility; personal records do not have an administrator override. Every native ancestor must also be visible and undeleted. Missing/deleted parents and cycles deny that branch. Corpus files use the existing company-scope and explicit-file-grant authorization; company membership, groups, the current user and unresolved grants keep their existing meaning. Both the Files app admission and the independent app's own current admission are required.

`selected_access.py` queries current rows with ORM refresh. Candidate pages scan at most 200 records (plus one lookahead), return at most 25 visible files, and search filename text literally. A cursor follows the last consumed scanned row, including invisible rows. Relevant ancestor traversal is limited to 32 levels and a 2-second work budget. The caller also bounds each database statement/lock to 1 second. Unfinished traversal or remaining scan work sets `incomplete`; an empty partial page must not be presented as a complete absence. Deep branches denied by the bound remain unavailable in this picker even if a less bounded source surface could enumerate them.

Only undeleted files sized 0–10,485,760 bytes are candidates. Metadata is file ID, display name (at most 255 Unicode code points), content type, byte size and an opaque SHA-256 `version`. The digest combines the existing `file_content_object_identity` and `file_content_acl_binding` contracts. Internal storage keys stay server-side. The host submits `expected_version`; authorize and each read independently recheck source access and version. Selection authorization rechecks after the audit flush. Reading rechecks after all upstream bytes are received and its socket closes, before returning a response. Changes during those waits fail closed. In-place object mutation that bypasses Files metadata/version updates is outside the source version contract and is not made safe by this adapter.

## Bounded storage transport

`selected_storage.py` preserves the normal Files storage client. It creates a separate MinIO public presigner with static Core credentials and an explicit signing region, so signing does not perform a region-discovery network call. It accepts only the configured HTTP(S) endpoint with no userinfo, query, fragment or base path. The resulting URL must retain the exact endpoint authority and path-addressed bucket/object key. It never accepts a user URL and never follows redirects. Alternate AWS endpoint rewriting and virtual-host bucket addressing are not supported by this adapter.

The signed URL is internal and expires after 30 seconds. A direct `httpx.AsyncHTTPTransport` performs cancellable socket I/O with HTTP/2, environment proxies and retries disabled. TLS hostname/certificate checks remain enabled; the CA selection preserves the existing MinIO policy of `SSL_CERT_FILE`, when set, otherwise certifi. No environment value, credential or real trust-store file was inspected during implementation. The selected-file-only `MIY_INDEPENDENT_APP_FILE_SELECTION_STORAGE_REGION` must match storage; its default is `us-east-1`.

The separate internal `read_pinned_object` entrypoint requires an explicit real
object version and reuses this same bounded transport. Missing, literal `null`,
malformed or oversized versions refuse before signing or I/O. Version identifiers
remain opaque and are signed as one exact `versionId` query value through the
public MinIO presigner; a presigner that drops or changes the version refuses.
An unavailable or permanently deleted version never retries or reads the latest
object. This entrypoint supplies transport behavior only: the Source publication
record must own the immutable key/file/version binding, and every caller must
still check current actor/app/resource authority. Publication persistence,
version-specific cleanup and prepared callsite integration remain structural
gates. Existing picker and legacy calls that omit a version retain their current
metadata/version contract; their behavior is not changed by adding this entrypoint.

Connect, read, write and pool timeouts are 2 seconds each, inside a 10-second total I/O deadline. Only status 200, a single exact numeric `Content-Length` and unencoded bytes are accepted. Declared length and actual bytes must equal source metadata and fit the 10 MiB cap; zero-length files are supported. Every response/socket/transport is closed on success, oversized/truncated/mismatched bytes, redirect, timeout, cancellation or other error. There is no abandoned synchronous SDK thread, pending retry queue or copied-object cleanup lifecycle.

The storage module admits at most four active reads per event loop/process. The Core route also holds a four-response permit until ASGI send completes or fails, so buffers retained by a slow downstream sender remain counted. Its 20-second response deadline combines cooperative cancellation with a monotonic check immediately before each ASGI header/body send. Synchronous SQL and a blocking ASGI sender cannot be preempted by an asyncio timer; the explicit check prevents newly handing over file bytes once that work returns after the deadline. Per-statement SQL timeouts remain the separate database bound. After headers, expiry propagates cleanup without a second response. These are admitted-response and object-size bounds, not a guarantee of exact wall-clock completion, 40 MiB RSS or client receipt; bytearray/bytes copies, HTTP chunks and server transport buffers can add memory. Bytes already handed to the sender cannot be recalled by later expiry or revocation.

The direct transport avoids the HTTP client's URL log path. A task-local filter on the pinned HTTP/1.1 transport loggers suppresses private request/response diagnostics, including signed redirect headers, without altering unrelated task logging. The platform's existing global HTTP logging guard remains unchanged. Only stable `storage_unavailable`/size errors leave the adapter, with sensitive exception causes suppressed. Do not add raw exception logging or expose signed URLs, storage keys or claims through URLs, audit payloads or app responses.

## Verification scope

`test_selected_file_storage.py` uses actual temporary TCP peers for slow headers/body, disconnect, cancellation, redirect, byte/length limits and DEBUG-log redaction. `test_selected_file_contracts.py` covers signed purposes, strict DTO/settings, bounded/slow bodies and real ASGI send/cancel/error/deadline permit lifetimes. `test_independent_app_files.py` uses isolated PostgreSQL for current sessions, generation/release permissions, Files admission/native/corpus ACL parity, version changes, post-audit-lock revocation and changes during a synthetic read. Existing Files content, manager/corpus and independent-app session regressions run alongside it.

These checks use synthetic bytes and owned disposable infrastructure. They do not claim a live operator MinIO instance, external customer file or production deployment was tested. Template/executor transport and actual browser/SDK behavior have separate owner evidence. No new database migration is required.

`test_pinned_file_storage.py` additionally checks opaque public presigning,
fail-closed version admission and actual temporary TCP reads with no latest
fallback. An owned disposable versioned MinIO probe exercises this product
entrypoint after overwrite, after a delete marker and after exact-version
removal. The retained evidence in `platform-redesign/VALIDATION.md` separates
these transport proofs from future publication and operational storage policy.
