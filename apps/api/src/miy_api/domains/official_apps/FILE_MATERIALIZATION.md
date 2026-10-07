# Strict Files materialization reader preparation

`file_materialization_roles.py` prepares one supplied fresh safe LOGIN for the
strict paired output reader in `files/materialization_source.py`. Preparation
metadata grants no runtime authority. It creates no role/function/schema,
performs no hidden COMMIT and starts no service, task, provider or worker.

All rights are column SELECT: canonical File17, public owner label3, corpus3,
safe SourceMetadata10, genuine Source outbox5, Core receipt7, Core event9/head7
and registered Source principal OID/name2. The constants in that module own the
exact list. Storage key, extraction error, private source identity/URI/raw
metadata, user credentials, sessions, extraction requests and other principal
fields are excluded. Source row locks and all Source/Core DML, partition reads,
sequence access, CREATE, memberships, grant options and definer EXEC are refused.

`prepare_file_materialization_reader(db, actor, role_name, expected,
expected_state)` uses current Core administrator/exact ownership admission and
unchanged hardened90/F2 guards. The caller owns atomic grants and administrator
audit. Exact new replay returns profile_prepared=True with no grant/audit;
previously reviewed exact F1 reader or F3 staging roles return False unchanged.
Partial/extra effective profiles refuse instead of being silently expanded or
revoked. A registered Source OID or retained name can never become this Core role.

Runtime paired-read behavior, actual identity/transaction/namespace admission and
Source/Core output correlation are owned by
[Core Files projection](../files/CORE_PROJECTION.md#strict-source-correlation-for-prepared-materialization).
This document owns role preparation and its exact privilege ceiling.

This profile authorizes observations only. Source stream/Core head locking,
Core partition lifecycle SHARE, bounded backend effects, durable effect unknown
reconciliation, job progress and runtime activation require separate explicit
contracts. F1 cached reader, F3 ingestion, Source extraction and Files descriptor
admission keep independent profiles; privileges are not implicitly combined.
