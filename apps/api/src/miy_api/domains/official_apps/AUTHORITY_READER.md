# Prepared official authority reader

`authority_reader.resolve_prepared_official_auth_context` is an inactive,
core-owned lookup seam. It accepts an opaque app-session credential and trusted
canonical logical app scope, then reuses current official binding, release
verification, independent-app identity and company/app admission rules. No HTTP
route, manifest, settings default or service selects this reader yet. Platform
login and the default official HTTP adapter remain unchanged.

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

HTTP/WS integration, non-launcher identity scopes, source-access/search/AI approval/
audit consumers, independent service credentials, queue ownership and old-writer
drain remain required in the [cutover plan](../../../../../../platform-redesign/OFFICIAL_API_CUTOVER.md).
This seam does not activate the suite or remove the inactive composition gate.
`tests/test_official_authority_reader.py` owns focused profile/current policy/
namespace/session-ownership cases; evidence belongs to `platform-redesign/VALIDATION.md`.
