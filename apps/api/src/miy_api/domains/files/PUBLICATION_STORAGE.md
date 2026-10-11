# Prepared Source object PUT

`publication_storage.publish_spooled_object` is an inactive internal transport.
Its caller supplies retained publication/operation UUIDs, one unique storage key,
an open Source-owned regular spool FD, exact size and SHA256. Arguments grant no
Source authority: durable attempted admission, current actor/app/resource/tree
policy and publication binding belong to the composing Source command.

The adapter allocates no IDs/key, retries no PUT, performs no delete and does not
enumerate versions or resume after uncertainty. The default upload, MinIO client,
selected reader, SQL roles and service wiring are unchanged.

Input is0..250MiB. Before dispatch, exact FD/type/size/digest/configuration checks
and bounded actual pread SHA/EOF verification complete. Each pread is<=64KiB;
the FD offset and lifetime remain caller-owned. Actual inode/device/size/mtime/
ctime are captured before/after. The same FD is streamed once with exact size,
SHA/EOF and metadata checks. No whole object is copied into memory. The two passes
read at most500MiB locally; synchronous regular-file reads/hash/presigning CPU
have no forced wall-clock cancellation guarantee.

MinIO's public presigned_put_object uses explicit region/static credentials and
disabled virtual style, so signing is local. Exact signed authority/path must
match the trusted endpoint/bucket/key. The endpoint accepts only HTTP(S), hostname
and root path, with no userinfo/query/fragment/controls. This is syntax checking,
not endpoint selection/SSRF authority. Trusted typed composition owns configuration.
The public presigner has no checksum-header parameter: SHA proof is local streaming
verification, not a server-enforced signed payload checksum.

Direct HTTPX AsyncHTTPTransport uses TLS verification, retries0, trust_envFalse,
HTTP/1.1 and no redirects/proxy. Total asynchronous socket-I/O time is120 seconds,
all connect/read/write/pool phases5 seconds. TLS CA selection preserves the normal
MinIO/selected reader policy: SSL_CERT_FILE when set, otherwise certifi, without
disabling hostname/certificate checks. Each owned response/transport cleanup has
its own5-second cooperative timeout, outside PUT+ACK120; at most2×5 seconds of
cleanup follow. No hard bound on synchronous work or cancellation-suppressing
cleanup is claimed. At most2 calls per process, including
multiple event loops/threads, occupy immediate nonblocking slots; overload has no
queue. No background thread is created or abandoned. Operation-scoped ContextVar
filters suppress private HTTPX/httpcore logs while other clients remain visible.

Known completion requires actual entire transmitted body, exact size/SHA/EOF,
HTTP200, exactly one non-null bounded UTF8 opaque x-amz-version-id and complete
ACK response<=64KiB. Zero-length input is actually verified before dispatch and
permits an empty-body ACK even if HTTPX skips iterating its empty stream. A positive
early200 without complete stream is unknown. Receipt retains only caller IDs,
size/SHA and VersionId (excluded from repr); no signed URL/key/header/body escapes.

PublicationStorageRefused means known pre-dispatch refusal. Any error after entering
the transport is conservatively PublicationStorageUnknown, even if no remote write
can be observed locally. Both expose only stable codes and caller IDs. Cancellation
remains a typed asyncio.CancelledError with the same IDs. Cleanup BaseException
cannot downgrade a known ACK or replace the original unknown/cancellation.
Non-Exception interruptions such as KeyboardInterrupt/SystemExit become fixed
storage_put_interrupted Refused before dispatch and Unknown after dispatch. Unknown
does not permit retry/new IDs or use of latest/ETag as a version. Caller-held durable
history and separately authenticated same-ID observation are required later.

Actual owned MinIO version/GET proof and independent review gate this transport's
acceptance. This module alone establishes no Source publication SQL/table, immutable
binding/apply, company audit, current authority, version-specific retention, upload
cutover, full recovery or service activation.
