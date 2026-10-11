# Fixed Core Files effect preparation and history

`file_materialization_effect_models.py` owns one independent Core table,
`core_file_materialization_operations`. It preserves exact Source/Core event,
output stamp, descriptor version, persisted keyword/vector target tuple, issuer
and database-canonical header digest. It stores no body, object key, credentials,
embedding, provider response or raw error. Source artifacts and the current Core
head are not foreign keys of historical records.

The caller retains operation UUID before the first transaction. Header is
immutable; state is `armed → complete` only. Event+generation-pair uniqueness
prevents identity replay. Separate partial unique constraints on File+keyword
target and File+vector target while armed prevent a later event from overtaking
an unresolved effect on either reused target. History cannot be deleted or
truncated, including empty statements. Complete requires a different top
transaction from SQL-stamped armed_xact_id and the original actual issuer.
This transaction witness does not prove a COMMIT ACK or an external ACK.

`miy_lock_file_materialization(event_sequence bigint, keyword_generation_id
uuid, vector_generation_id uuid, expected_partition_metadata_version integer)`
is fixed Core-only SECURITY DEFINER and returns matched partition UUID only.
All arguments are required. Actual safe LOGIN/no membership, registered Source
OID **or retained name** exclusion, READ COMMITTED and current effective required
rights are checked. No GUC, role name, model decision or preparation metadata
grants authority. Driver autocommit/fresh ownership is the Python runner's
separate admission boundary.

Lock order is genuine Source stream → exact active Files/company descriptor
SHARE → **shared existing pair-control advisory only** → actual opensearch
generation SHARE → qdrant generation SHARE → exact current Core head SHARE →
operation/jobs. Both generation states must agree and be baselining or replaying;
current key, target and schema tuple is bound. No backend advisory gate, Source
row lock/write, head upgrade, event acceptance or generation transition occurs.
Private owner uses UPDATE only on descriptor.state, generation.state and
head.projection_version to obtain SHARE; effect callers have none of those rights.

The public composition must invoke the cap before operation-row DML. Raw SQL
UPDATE may already hold its operation row before the row trigger calls the cap;
that inversion is outside the reviewed composition lock-order proof. Trigger
refusal is not a general deadlock guarantee for arbitrary clients.

Four exact private functions and three exact triggers are installed by append
`file_effect_20261007` after `file_source_partition_20261007`. Source90 and old
F2/company/Files SQL bodies remain unchanged. The fixed generation guard holds
**any state change**, target identity rewrite or watermark change while any armed
record names that target, even no jobs/FAILED jobs or empty Source inventory.
Exact no-op is allowed. Protected generation mutations require READ COMMITTED;
VOLATILE fresh SPI reads must see an arm committed while an updater waited.
Root reconciliation separately counts armed records before caught_up/cursor/
validation/cutover, including empty batches. Complete history alone holds no
lifecycle transition and does not require current Source/artifact/head validity.

`file_materialization_effect_roles.py` owns exact constants and attestation:
fixed prosrc hashes/language/security/path/flags, trigger relation/type/enabled/
UPDATE-column list/args/predicate/constraint flags and exact two non-internal
triggers on the new operation table, event-pair and both partial hold indexes
(including absence of expression/include keys), minimal owner and existing
direct/effective grants. All4 functions
revoke PUBLIC; only the one cap can be explicitly executed by a reviewed effect
LOGIN. The other3 functions have no other execute grantee.

`install_file_materialization_effect_guard(db, actor, owner_role_name, expected,
expected_state)` accepts one supplied fresh safe NOLOGIN. Owner SELECT is58 fixed
columns: Source File identity/stamp7, Corpus3, safeMetadata3, outbox5, receipt7,
Core event9/head7, Source principal2, descriptor6, generation6 and operation3
(state/keyword_generation_id/vector_generation_id only). NEW/OLD row values need
no operation-header SELECT. Owner UPDATE is the3 SHARE columns only. It owns
only the4 new functions and no table, with no Source DML, job, sequence, old
private EXEC, Auth, AI, provider or audit grants.

`prepare_file_materialization_effect_principal(db, actor, role_name, expected,
expected_state)` accepts one supplied fresh safe LOGIN. Role SELECT is125 exact
columns: strict reader63, generation6, descriptor6, operation29, Search11 and
RAG10. Caller INSERT is22 input-header columns; UPDATE is operation.state and
both jobs' status/attempts/last_error/next_retry_at/updated_at5 only. The sole
new cap EXEC is explicit. Direct Source SHARE/DML, head/generation/partition DML,
Source private columns/Auth/request/storage, job payload/trace/error reads,
event/receipt INSERT, sequence, CREATE, memberships and grant options are refused.
The code owns the exact column names, including Search.entity_type for older
unfenced outstanding File jobs; counts do not authorize unspecified columns.

Preparation uses current administrator/exact ownership and unchanged Source/F2
guard contracts, creates no role, and owns no COMMIT. Caller owns atomic grants
and administrator audit. Exact new replay returns profile_prepared=True with no
grant/audit. Exact prior READ/F1/F3 profiles return False unchanged. Registered
Source OID/name refuses becoming Core. Partial/extra profiles refuse; no existing
principal receives an implicit privilege union.

Runtime once-permit/owned Session/COMMIT ACK and bounded synthetic-backend
composition is owned by `retrieval/prepared_file_effects.py` and
`retrieval/prepared_file_materializer.py`, linked from
[Core Files projection](../files/CORE_PROJECTION.md). SQL enforces authority,
immutable correlation/history and lifecycle holds; it cannot establish remote
provider success. First construction/compute/effect requires acknowledged new
arm and its original live once permit. Unknown arm/effect/complete outcomes keep
the same UUID/header digest; history/absence produces no retry or new permit.
Complete and exact existing job resolution share one Core COMMIT after both
known backend ACKs and final fences. No automatic retry/lease/target replacement
or provider/service/worker activation is installed.

Downgrade requires draining, explicit cap-grant retirement and an empty history
table. Any armed **or complete** history blocks removing this schema. Test-owned
inactive baseline capture asserts this table empty and excludes its data from
pg_dump. Only the verified disposable atomic reset retires/restores its exact
statement guard; reset failure rolls back history and trigger DDL. Production
COPY/TRUNCATE admission is unchanged and remains enforced.

The inactive boundary passed locally owned restricted PostgreSQL validation:
83 unique Data authority/concurrency/runtime cases,72 Source session-impact cases
and175 existing schema/role/fixture cases, with failure history and independent
review retained in the redesign evidence. Controlled102 Python cases are separate
from SQL authority proof. No shared runtime role, service or provider was enabled.
Prior strict READ/Source/descriptor checks retain their own temporal scope. Immutable Source object publication, full bootstrap/tree/service/auth/
ACL/AI gateway/audit and operational activation remain independent gates.
