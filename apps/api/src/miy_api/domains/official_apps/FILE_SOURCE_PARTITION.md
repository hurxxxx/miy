# Fixed Files Source descriptor admission

`file_source_partition_roles.py` owns explicit preparation of the fixed
`miy_read_file_source_partition(uuid,integer)` capability added by the append
`file_source_partition_20261007` migration. It does not activate a service or
widen the original company Source reader, F3 Core-only reader or existing roles.

Both arguments are explicit. A NULL managed version accepts only the supplied
active Files/company default descriptor with metadata_version>=1. A positive
integer accepts only the supplied active Files/company nondefault managed
descriptor with that exact version. Missing UUID, invalid version/kind, personal
scope, namespace/version drift or inactive state refuses. Return is the matched
UUID only. Descriptor metadata grants no actor/app/resource access and performs
no allocation.

The actual safe LOGIN/session_user OID/name resolves its registered Source
generation/artifact; unchanged private producer admission retains current
ownership/principal SHARE. The matched descriptor holds FOR SHARE through the
caller Source COMMIT. GUCs, supplied metadata and returned setup records never
replace those checks. Caller uses READ COMMITTED. Historical request observation
and genuine event receipt replay retain their existing separate contracts.

The supplied distinct safe NOLOGIN owner has descriptor SELECT on seven fixed
columns, principal SELECT(role_oid,role_name,generation,artifact), UPDATE(state)
solely for PostgreSQL row SHARE, and one existing private producer-admission
EXEC. Source caller gets no Core descriptor SELECT/UPDATE or direct row SHARE.
Fixed body/language/signature/no defaults/volatile/non-strict/non-leakproof/
parallel-unsafe/path/PUBLIC revoke, owner attributes/membership and effective
column/EXEC ceiling are attested before grants together with unchanged
hardened90 and F2 five-body/eight-trigger contracts.

`install_file_source_partition_guard` requires current Core admin and exact
expected ownership/draining. `prepare_file_source_partition_principal` requires
a pristine supplied safe LOGIN/current immutable Source identity and explicitly
grants the fixed F2 Source88+2/request/current-policy/AuthSession5/admit+digest
profile plus this one capability EXEC. No role is created; no hidden COMMIT,
service or queue is started. Caller rollback restores preparation/audit.
Existing exact base/company/F2 registered roles return profile_prepared=False
with zero GRANT/audit; already-new exact replay returns True with zero GRANT/audit.
Partial/unknown grants, credentials, whole policy tables, other definer EXEC,
grant option, membership or CREATE refuse. Preparation metadata is not runtime
authority. Source88 already includes full business SourceMetadata fields; this
profile adds no new cross-Core/private policy/credential privilege.

Core descriptor setup and retained-UUID unknown observation belong to
`retrieval/FILE_PARTITIONS.md`; setup receipts are provisional. Source separately
checks actual corpus/parent/target binding and current live actor/session/app/ACL
after waits and storage I/O. The managed argument comes from the actual locked
Source corpus version; standalone validation has no stored version and accepts
the current valid default. This capability preserves lifecycle through commit;
it does not serialize Source tree insert/delete, prove immutable objects or
authorize upload/replace cutover. Source-local aggregate and publication gates,
current service composition and operational rollout remain separate.

The append is inactive until explicit reviewed owner/profile preparation.
Downgrade requires current hardened ownership/draining and explicit retirement
of all non-owner capability EXEC grants; original28 migration bodies/history,
canonical90, F2 and F3 function/role contracts remain preserved.
