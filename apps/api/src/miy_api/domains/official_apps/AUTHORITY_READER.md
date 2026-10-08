# Prepared official authority reader

`authority_reader.resolve_prepared_official_auth_context` is an inactive,
core-owned lookup seam. It accepts an opaque app-session credential and trusted
canonical logical app scope, then reuses current official binding, release
verification, independent-app identity and company/app admission rules. No app
manifest, settings default or deployed service selects this reader. A trusted
server-only HTTP/Docs/Whiteboard WebSocket assembly can explicitly select it using a separate auth factory;
platform login and the default official HTTP adapter remain unchanged.

## Explicit inactive HTTP assembly

`register_api_routers` accepts paired `official_auth_session_factory` and
`official_auth_max_concurrent_reads` options only for the official composition.
With neither, the existing HTTP adapter remains selected. Partial configuration,
another composition, a non-callable factory or a non-positive/non-integer budget
refuses assembly. No request, app manifest or environment flag chooses these options.

The prepared dependency validates owned canonical scope and bearer credentials
before allocating the auth Session. It invokes the unchanged reader in an AnyIO
worker with a private limiter sized by the auth Engine owner, separate from the
business Source factory and pool. The limiter is created in the ASGI async context;
its budget bounds executing reads, not HTTP waiters or other service workers.
An outer read permit surrounds a public AnyIO TaskGroup; its private child shields
the thread await and uses a per-call worker limiter. The group joins reader and
cleanup before releasing admission under supported AnyIO scope cancellation and
raw/repeated host request-task cancellation. A canceled admission waiter creates
no Session. Original child exceptions are raised outside the group, without
changing policy or cancellation into an ExceptionGroup. The child is not exposed
for direct cancellation. Hard process kill, event-loop shutdown and an uncooperative
driver/cleanup hard deadline are not guaranteed by this composition.
Existing SQL timeouts are not a whole-request deadline. Reader control or SQLAlchemy
failures return a fixed localized503 without private details or a broad-reader
fallback; current credential/admission401/403 and cancellation remain distinct.

The returned detached context is cached only by the existing request dependency
chain. Current app policy and resource ACL are still enforced by the real Source
handler. A successful lookup does not freeze permission through later waits or
writes. This assembly does not install an operational auth role, activate the split
ASGI artifact or complete the business Source privilege policy. Removing the options
restores default assembly; runtime failure never selects that default as recovery.

## Explicit inactive collaboration assembly

The same registry-built callable accepts public Starlette `HTTPConnection` and is
retained only in server-owned application state. Prepared Docs and Whiteboard
WebSockets reuse that exact callable and its read limiter; they do not construct a
Request, another reader or a second pool budget. The route owns the fixed `docs`
or `whiteboard` scope. Caller headers, query scope and auth-frame extra fields do
not choose authority. Query credentials remain refused by the existing handshake.
The small `websocket_auth.py` adapter belongs to this domain; business routers do
not import an API composition root.

Prepared lookup finishes before initial business Source allocation. The unchanged
Source page/board loaders still enforce current app admission and edit ACL. Docs
also retains its current writer identity, initial transaction fence and frame
writer check. A read share cannot open an edit room. Every Yjs receive, outgoing
send and idle monitor performs a fresh prepared lookup before Source ACL access;
a connected socket and an earlier detached context are not continuing grants.
The initial actor must remain the same on subsequent checks. The existing public
Yjs authorization callbacks, room slots, hub cleanup and persistence remain owned
by their original modules.

Credential/policy denial preserves existing handshake4401/4403/4404 and per-frame
access revocation1008. Reader control/SQLAlchemy failure chooses private1013
`official_authority_unavailable` without Source allocation, platform-auth fallback
or fencing another client's room. Docs writer failure retains its separate1013
writer fence. Cancellation remains cancellation and uses the accepted structured
reader cleanup contract. Removing prepared state during a connection refuses its
next prepared check; it does not adopt the legacy reader. Default construction
keeps the original platform-token collaboration helpers.

`tests/test_prepared_official_ws_auth.py` exercises real migrated PostgreSQL and the
exact14/87 auth role, delegated/source/binding/app/user revocation, actual Source
edit denial and Docs writer drain. Its business Source factory is the isolated
legacy fixture, not an operational minimal Source role. Its room/bus are synthetic
and invoke the unchanged Yjs transport callbacks; no live relay, codec, room
persistence, service deployment or operational authority is accepted by that proof.

## Explicit inactive Whiteboard ACL reads

An official assembly that already supplies prepared auth can also explicitly
supply `official_whiteboard_source_session_factory` and
`official_whiteboard_source_max_concurrent_reads`. Both are required together.
The captured callback has a separate positive Source read budget. HTTP auth and
Source reads reuse the public domain `owned_read.run_owned_read` structured worker;
the auth limiter and its existing cancellation and failure behavior remain unchanged.
Default assembly supplies neither Source option and retains its original callback.

The Source callback refuses borrowed, cached, pending, connection-bound or routed
Sessions before SQL or cleanup ownership. A factory must use standard public
`Session.get_bind`, one Engine for the fixed current ACL model set, PostgreSQL
READ COMMITTED and non-autocommit. Owned reads use a read-only transaction,
canonical local search path and the existing five/fifteen-second SQL limits.
Owned rollback/close attempts finish before the callback returns; a failure
attempts invalidation and cannot replace the original policy or cancellation outcome.
SQL/control failures return the same private localized503, without a default
Source factory fallback. Policy403/404 and cancellation retain their types.

`collab_source_access.CORE_POLICY_READ_COLUMNS` records eight existing Core policy
tables and twenty safe columns, a subset of the existing Source policy contract.
Current app, user, admin, local/HR group and registered target predicates are
reused. The ACL-only board loader selects five fields with deferred-column and
relationship raise guards; it does not load the scene, title, owner or share-user
graphs. Existing PMS/Meeting target adapters still load their original Source
models. No predicate is replaced by a detached auth context.

The callback reuses the existing private `writer_roles._role` catalog check for
direct nonprivileged LOGIN attributes, membership, ownership and parameter grants.
This reuse is not a full privilege-manifest attestation or a new role preparation
API; the helper's existing namespace-prefix checking limits remain. Focused tests
use a disposable ACL-read login with column-only Core/board reads and SELECT on
nine existing Source target/share tables. They do not establish an operational
minimal Source or hub role, and product code creates no roles or grants.

After Source read cleanup, the route calls the same prepared auth dependency
again and requires the original actor and source-session identity before continuing.
Current source-session or app denial across a Source wait therefore refuses the
frame. This is a current admission check, not an atomic freeze of ACL until a
later write. Original room initialization, scene/Yjs state, hub persistence and
their global business Source factory are unchanged. Those lifecycle operations,
the full Source privilege profile and operational activation remain cutover work.
`tests/test_prepared_whiteboard_source_access.py` owns the bounded ACL-role,
namespace, ownership, wait/revocation and cancellation checks. Its room/bus and
initialization factory remain isolated synthetic business fixtures.

## Ownership and current authority

The caller supplies a factory for a fresh **auth-only** SQLAlchemy Session,
separate from the business Source Session. Before SQL or cleanup ownership,
the reader requires standard public `Session.get_bind`, one Engine for every
authority mapper/table, an empty identity map and no active transaction or
pending work. Custom routing, connection binds, cached or active caller sessions
are refused without clearing objects or rolling back their work.

The owned Session requires PostgreSQL, actual READ COMMITTED and non-autocommit.
The first isolation read is `SHOW transaction_isolation`, so a caller search path
cannot replace a same-signature function. Its transaction is read-only, with
`pg_catalog, public, pg_temp` and local 5-second lock/15-second statement limits.
Persistent authority is read from public even when a pooled connection has
temporary shadow tables.

The existing lifecycle receives a typed, server-only optional source-user loader.
Explicit `None` keeps the current full-graph reader. The prepared path loads
User id/status/password-change policy/primary organisation/display name/full
name/email/locale/time zone and selected AuthSession id/user id/expiry/revocation/
impersonation fields. It does not load password hashes, source credential hashes,
other login sessions or organisation relationships. These original models form
the same `AuthContext`; no second authentication or identity protocol is introduced.
Final app admission is rechecked; a system-role change during that check refuses
the lookup instead of returning the earlier roles. There is no implicit retry.

Success returns detached models with only safe scalars loaded. Deferred credential
columns and relationships cannot issue later SQL. Lookup does not update
last-seen, write audit or commit. Rollback/close failures cannot mask denial or
cancellation; cleanup failure attempts invalidation, and the owned Session is
never reused. Delegated credential revocation/expiry is read again before detaching;
both delegated and source-session expiry are checked after cleanup. A lookup
result is not durable authority: business resource ACL and write/approval actions
must still check current authority in their own transaction. Revocation after
return is not frozen by this reader.

## Restricted login profile

`AUTHORITY_READ_COLUMNS` in the module owns the exact 14-table column manifest,
including all columns currently read by reused installation/release/binding/
verification ORM queries. Only the app-session hash used for lookup is included;
the source login hash is excluded. Do not widen this profile to run a full user
graph or business handler.

The actual login must be direct, NOINHERIT, nonprivileged, without role membership,
persistent object ownership or privileged parameter grants. Existing owned
principal/sequence checks are reused. Current-database non-system schemas are
checked for unexpected reads, table/column DML, grant options, schema CREATE,
sequence privileges and executable SECURITY DEFINER/owned/grantable functions.
All required reads must be present with no other application-table reads. TEMP is
permitted; temporary tables do not replace canonical reads. This is not an
inventory of other databases or host privileges.

The reader additionally checks literal `pg_` namespace prefixes and relations
without user columns. The existing principal helpers use a broader SQL LIKE
pattern and do not own this exact read manifest; those helpers remain unchanged.

The product does **not** create, grant or configure operational roles. Tests
provision fresh roles in an owned disposable migrated database. Actual role
preparation, credential distribution and a matched independent service artifact
require separate approved delivery work. This auth-only profile cannot be
assigned as the business Source writer profile.

## Remaining cutover

Operational HTTP/WS activation and complete Source/hub privilege profiles, non-launcher identity scopes, source-access/search/AI approval/
audit consumers, independent service credentials, queue ownership and old-writer
drain remain required in the [cutover plan](../../../../../../platform-redesign/OFFICIAL_API_CUTOVER.md).
This seam does not activate the suite or remove the inactive composition gate.
`tests/test_official_authority_reader.py` owns focused profile/current policy/
namespace/session-ownership cases; evidence belongs to `platform-redesign/VALIDATION.md`.
`tests/test_prepared_official_http_auth.py` owns explicit HTTP assembly, separate
restricted auth-role admission, real current Source ACL and cancellation boundaries.
