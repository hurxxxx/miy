# Independent app data profile v1

`web-api-v1` remains stateless. `web-api-postgres-v1` adds core-owned PostgreSQL record storage and the `data:read`/`data:write` permissions. Unknown profiles fail manifest validation. The [private notes starter](../../../../../../templates/independent-app-data/README.md) is a consumer, not a special case in the gateway. Worker processes, object storage, app-authored SQL and custom relational schemas remain unimplemented extensions.

## Setup and ownership

The core API and trusted local delivery executor need `MIY_INDEPENDENT_APP_DATA_POSTGRES_DSN` and `MIY_INDEPENDENT_APP_DATA_CREDENTIAL_KEY`. Both default empty; empty configuration closes only the data profile. Install them in the ignored core service configuration, never an app checkout/container, Workbench task, browser or document. The DSN is an operator-owned administrative connection to a **dedicated app-data PostgreSQL cluster**; the credential key needs at least 32 high-entropy characters and durable secret-manager backup. Standard PostgreSQL connection/TLS options apply. A data request never provisions storage.

Before enabling that cluster, its operator must restrict `PUBLIC CONNECT` on all connectable databases, including maintenance/template databases. The provisioner inspects privileges and **refuses** an insecure cluster; it never revokes privileges on existing databases. Do not point it at the current MIY/core/dev cluster and expect automatic hardening. PostgreSQL defaults `PUBLIC` to database connection rights, so merely giving each app a different login does not isolate databases. See [PostgreSQL privileges](https://www.postgresql.org/docs/17/ddl-priv.html).

Every installation UUID deterministically names its own database, migration login and gateway DML login. Development and production installations therefore cannot share rows. A core ownership marker binds installation, app and environment. Foreign objects, unexpected memberships/role privileges, schema/checksum drift and cross-database `CONNECT` privileges cause failure. New databases start with connections disabled, then receive only their intended grants before enabling connections. Existing core/dev databases are never altered. Roles/DBs left by a crash before identity marking require operator inspection, not automatic adoption or deletion.

The key derives distinct passwords with domain-separated HMAC; passwords are never supplied to an app. Changing the key is **not** an automatic rotation: existing role login fails and the provisioner does not rewrite passwords/grants. Rotation requires a scheduled core-operator procedure that backs up configuration, updates both installation roles and the API/executor key consistently, validates identity/isolation, then retires the old key. Keep the old key for rollback until validation completes. Do not rotate only one service or delete the key during code rollback.

## Gateway contract

`/api/v1/independent-apps/_data/{collection}` lists/creates records; `/{record_id}` reads, updates and deletes them. `_data` cannot collide with an app ID. All calls require an app Bearer session plus `installation_id` and exact `audience`; the server revalidates source login, app grant/admission, installation generation, verified release and data profile on every call. A service API key, platform token, user ID in JSON or manifest declaration does not authorize data access.

The gateway derives the owner from that identity, chooses its installation database and uses the least-privilege DML role. Arbitrary SQL is not accepted. Fixed parameterized statements include owner predicates; forced PostgreSQL RLS adds another boundary. Setting a PostgreSQL session variable would be forgeable if apps held that credential, which is why credentials and query execution stay in the core gateway. DML cannot create tables, alter RLS, modify migrations or connect to other databases. Every connection checks current cross-database privilege drift.

Collections match `[a-z][a-z0-9_-]{0,63}`; record IDs are UUIDs. Payloads are JSON objects of at most 16 KiB; HTTP writes are streamed with a 20 KiB bound. Unknown top-level fields fail. Lists use bounded keyset pagination (default 50, maximum 100). `PUT` takes `{payload, expected_version}`; `DELETE` takes `expected_version` in its query. A missing/mismatched version fails without writing. Rows are always private to the source user within the installation; sharing requires a future explicit ACL contract. App-owned business validation belongs in the app, such as the private-notes text limit.

`POST` optionally accepts `record_key`, an exact, nonempty printable string of at most
256 UTF-8 bytes; whitespace-only values, controls and surrogates are rejected. The
gateway does not trim or change case. A fixed Core UUID namespace and the authorized
installation/user/collection/key determine the record ID. PostgreSQL's existing
primary key permits one concurrent create: the new row returns `201`, and an existing
key returns `409` without exposing or replacing its payload. Omit the key to retain
ordinary random-UUID creation. `GET /_data/{collection}/by-key?record_key=...` uses the
same authorized scope and requires `data:read`, returning the normal record or `404`.
The app can inspect that key after an uncertain create; it must not automatically
repeat a write. Keys are create-only and cannot be supplied to `PUT`.

This is uniqueness for a currently existing row within one source user, installation
and collection, not organization-wide uniqueness or a durable request journal.
Deleting a row allows that key to be created again at version 1. Existing unkeyed
records are not converted. Business normalization and agreement between a key and
payload belong to the app. The schema, migration checksum, RLS and update/delete
version checks remain unchanged.

## Migration and recovery

Only the fixed core `data_store.MIGRATION` is executed, under a separate migration role, before runtime activation. Its version/checksum and installation identity are stored inside the application database. A durable `migrations` journal binds each deployment request ID to immutable artifact digest, core schema version/checksum and commit time. Transactions keep DDL, metadata and journal changes atomic. Same request and artifact are idempotent; a request reused with another artifact fails. Schema/checksum drift is never silently repaired. Delivery's PostgreSQL request journal owns operation failures and uncertain executor outcomes.

Code rollback requests the previously verified artifact and records another compatibility check against v1. It never downgrades schema, drops the DB or restores development rows into production. Stop/retire/failed deployment also retain data. Data backup/restore is a separate operator-owned operation using the database and roles belonging to the exact installation. No automatic schema downgrade or destructive database cleanup is exposed.

Run `uv run --frozen --directory apps/api pytest -q tests/test_independent_app_data.py` for a disposable PostgreSQL container using an already-local `postgres:<pg_dump-major>-alpine` image (no pull). For an explicit already-local immutable test image, supply both `MIY_TEST_APP_DATA_POSTGRES_IMAGE=sha256:<image-id>` and `MIY_TEST_APP_DATA_POSTGRES_MAJOR=17|18`; the fixture verifies the image identity and real server major. This opt-in affects only disposable test storage. The fixture owns and removes its exact container and ephemeral data; it does not alter the existing development cluster. Tests cover default-grant rejection, real role/database separation, per-user CRUD, RLS, optimistic updates, artifact/idempotency/checksum binding, key mismatch and data survival across code rollback. API-level tests additionally cover token/grant revocation and request bounds. Production installation activation remains outside the current local executor contract.

`MIY_TEST_INDEPENDENT_DOCKER=1 uv run --frozen --directory apps/api pytest -q tests/test_independent_app_data_docker.py` additionally builds two immutable notes images with the trusted builder, executes the real app/proxy/session/storage path, and checks data retention after image rollback. It needs the already-local approved toolchain and nginx image IDs recorded in `test_independent_app_runtime.py`. Its synthetic API listener binds only the local Docker bridge and all fixture resources are removed. Run heavy Docker/PG validation sequentially; a timeout remains a failed/uncertain operation, never a reason to mark an artifact verified.

## Declared record search

An optional `search` declaration on `web-api-postgres-v1` lists at most eight collections,
each with one to eight top-level string `text_fields` and explicit `keyword` and/or
`semantic` modes. Undeclared collections/modes fail closed. `search:read` additionally
requires `data:read`; the owner must grant both. Omitted/null search keeps the original
manifest serialization, data-v1 schema checksum and release digest unchanged. There
is no custom document store, query DSL, arbitrary SQL, app-selected model or backend
URL/credential. Apps that do not declare search keep their current data behavior.

`POST /api/v1/independent-apps/_search/{collection}` requires the same current app
session, exact installation/audience and active trusted release as `_data`. Its body
is `{query, mode, limit}`: a nonblank query up to 2,000 code points/8,000 UTF-8 bytes,
`keyword` or `semantic`, and a limit from 1 to 20. The starter's same-origin
`POST /api/search/{collection}` fixes installation and audience; the browser SDK's
`searchRecords` uses this adapter with only the in-memory app token. Tokens never
enter URLs or browser storage. Response items contain current `RecordOut` and a
score, plus `indexing_pending`; this flag reports unfinished/held indexing, not
transactional read-after-write search consistency.

Only Core preparation adds the separately checksummed search schema, projection
heads, generation definitions and outbox inside the installation's existing database.
The original data-v1 migration remains immutable. A record write/delete and its
monotonic source sequence/outbox publication commit together under the same owner
RLS transaction; failed CAS writes publish nothing. Projection sequences survive
record deletion and keyed recreation, even when the recreated row starts at version

1. A generation fence protects concurrent backfill; source rows and older search
   resources are preserved. Search API binding selection follows the **active release's**
   search declaration, so registering/building another candidate cannot replace current
   runtime search. Equal declarations and the same approved embedding profile reuse a
   ready generation; changed definitions/profiles prepare separate resources.

The Core-only `search_consumer.prepare_binding` takes verified development artifact
and server-owned workspace/installation identity. 검색 세대는 설치 행 잠금 아래
기존 검색 세대의 최댓값 다음 값으로 할당하며, 설치 admission generation과 분리된다.
앱 health/UI 검사 실패 뒤에도 준비된 리소스와 과거 세대를 보존한다. 선언·승인된
embedding 설정이 달라지면 새 검색 세대를 준비하고, 미확정 preparing/unknown 작업이
있으면 새 세대로 우회하지 않고 보류한다. 동일 선언·설정의 ready 재사용은 유지한다.
Resource names and ownership
markers bind that identity and search/profile generation. OpenSearch identity also
includes its native index UUID; Qdrant uses an exact Core owner sentinel and vector
configuration. Semantic dimensions are resolved through the existing approved
role-specific Inference Gateway embedding profile, never app input or a fake/local
fallback. The private consumer entrypoint `python -m
miy_api.domains.independent_apps.search_consumer serve` polls enabled installations;
`once --installation-id <UUID> [--release-id <verified development candidate>]`
allows a bounded materialization/warm pass. Operators provide existing typed Core
settings privately. Service ownership/network configuration belongs to the Core
workspace controller, not the app or Workbench task.

Each projection is hydrated from the latest PostgreSQL record under its exact owner
and fenced while engine phases are acknowledged. Keyword/vector filters fix owner,
collection and resource identity. Query results are then rehydrated under gateway
RLS/current source sequence; engine payloads and stale/deleted/foreign hits are never
returned as authoritative app records. Empty declared text removes its search
materialization without deleting the original row. Unknown engine/model effects
retain their exact event and acknowledged phases as `held`; no new operation ID or
automatic replay pretends success. An operator must inspect/reconcile held effects;
other records/generations remain eligible.

Shared OpenSearch/Qdrant credentials stay in Core. When the shared engines lack
per-resource authentication, name prefixes/markers are **not** network authorization:
app execution must retain its private network and fixed Core gateway, and the shared
engine listeners must be restricted to Core. The current app API grants no raw
engine access, cross-user search, arbitrary embedding settings or general network
capability.

`MIY_INDEPENDENT_APP_SEARCH_ENABLED` defaults to `false`; closed configuration fails
before constructing engine/embedding clients. Operators enable it only after the
owned workspace profile and restricted engine listeners are ready. This release
prepares search for development workspaces/stable development installations;
production search provisioning is deferred. Existing search-free production apps
retain their current behavior.

Temporary workspace cleanup is a separate Core-owned action after the controller
proves exact workspace ownership, merged development execution, stopped admission
and stopped writers. Search generations are stopped and exact owned resources checked
before removal. The binding first commits a `verified` cleanup phase, then records
`keyword_removed` and `vector_removed` only after observing each target's absence.
A lost acknowledgement/partial removal remains `cleanup_pending` with that durable
phase. Resumption rechecks the original OpenSearch UUID and Qdrant owner marker;
foreign replacements, uncertain provisioning and missing cleanup proof remain held.
It never invents a new deletion operation or adopts an unmarked resource.
`PostgresAppData.remove_temporary` accepts development only and
requires a durable bounded catalog identity receipt before disabling DB connections.
It verifies ownership markers, native OIDs, schema checksums, memberships/privileges
and no active connections, then uses `DROP DATABASE` **without FORCE** and drops only
its exact roles. Positive catalog absence is safe for a never-provisioned workspace;
mixed absence without the original receipt is held. Partial failures retain receipts
for explicit reconciliation. Ordinary installed/stable development data and all
production data are outside automatic workspace deletion authority.
