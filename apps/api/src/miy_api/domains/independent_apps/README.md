# Independent applications, protocol 1

This domain owns the new source manifest, durable platform projections and app session exchange. Existing built-in apps continue using `packages/contracts/app-contracts.json`; their admission and resource ACLs remain in force. The root [redesign plan](../../../../../../platform-redesign/PLAN.md) tracks migration, implementation status and unfinished acceptance work.

## Authority and compatibility

`contracts.AppDefinition` is the versioned wire schema. Generate its distributable JSON Schema with `uv run --frozen --python 3.12 --directory apps/api python ../../scripts/generate-independent-app-schema.py`; add `--check` to verify both the shared contracts and standalone Workbench copies. Runtime validation also checks canonical URLs and relative paths, so JSON Schema alone is not admission authority.

The app repository owns `app.manifest.json`; an authenticated owner registers its projection with a full source revision. Definition updates compare both `expected_digest` and `expected_source_revision`, and reject stale updates. Built-in IDs cannot be replaced. Official definitions require the current platform-admin role even if their original owner's role was later removed. Invalid or deleted source manifests never remove an existing installation.

PostgreSQL stores definitions, immutable release candidates (manifest snapshot, source revision, digest-pinned artifact), installations and hashed session credentials. The additive registry/session revision is `independent_apps_20261006`; `independent_delivery_20261006` adds trusted build evidence, deployment requests and capacity reservations; `independent_delegation_20261006` adds owner-bound Workbench grants and delegated build intents. Rollback of application code does not require a schema downgrade. Explicitly downgrading this schema deletes its new tables and their data; back up first.

The implemented profiles are `web-api-v1` and `web-api-postgres-v1`, with SDK version 1. `identity:read` is supported by both; `data:read` and `data:write` require the PostgreSQL profile and explicit installation grants. Its [data contract](DATA.md) owns database isolation, record ACLs and schema versioning. Unknown properties or versions fail closed. Manifests do not declare host commands, volumes, elevated privileges, production credentials or arbitrary capability grants. Framework-neutral HTTP and browser contracts are separate from the recommended [React/Vite + FastAPI starter](../../../../../../templates/independent-app/README.md).

## Registration, admission and sessions

All definition/release/installation mutations require the existing MIY bearer login. Owners can configure individual development previews for themselves. Platform admins control broader audiences and the company-wide switch. One production installation per app is enforced by a PostgreSQL partial unique index; separate development worktrees may have separate installations and origins. Origins are globally unique between installations so one app origin cannot also be another app's security principal.

`CompanyAppControl.enabled` is the existing global company gate. `AppInstallation` owns environment-specific enablement, audience, individual/group grants and granted capabilities. Every launch and protected app request checks the current company gate, account state, parent login expiry/revocation, installation state and audience. Installation policy changes increment a generation, invalidating pending codes and existing sessions. Impersonated portal sessions are explicitly unsupported for independent apps in protocol 1. App sessions never authenticate ordinary MIY product endpoints or bypass resource ACLs.

| Endpoint                                                  | Authorization / purpose                                                                                                                                |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /independent-apps/catalog`                           | MIY login; own/manageable definitions and admitted installations only; `launchable` is current admission, and `catalog_revision` detects changed pages |
| `PUT /independent-apps/definitions`                       | Authenticated owner, or platform admin for an official definition; compare-and-swap update                                                             |
| `POST /independent-apps/{app_id}/releases`                | Owner; records an unverified, digest-pinned candidate, never asserts deployment                                                                        |
| `POST /independent-apps/{app_id}/installations`           | Owner's private development preview or admin configuration                                                                                             |
| `PUT /independent-apps/{app_id}/installations/{id}`       | Same authority; invalidates previous app sessions                                                                                                      |
| `POST /independent-apps/{app_id}/deployments`             | Owner login; idempotent development deploy/rollback intent, current generation and previous release fence                                              |
| `GET /independent-apps/{app_id}/deployments/{request_id}` | Owner login; durable intent/status, never daemon credentials                                                                                           |
| `PUT /independent-apps/{app_id}/company-control`          | Platform admin; company-wide kill switch                                                                                                               |
| `POST /independent-apps/launch`                           | MIY login and live admission; code bound to installation, source login, generation and S256 challenge; at most 60 seconds                              |
| `POST /independent-apps/exchange`                         | One-use code, verifier and exact registered app origin; atomic consumption; scoped token for at most 5 minutes                                         |
| `GET /independent-apps/session`                           | App bearer plus expected installation/audience; live authority checked on every call                                                                   |
| `/independent-apps/_data/{collection}[/{record_id}]`      | App bearer and data capability; owner-scoped bounded CRUD under the [data contract](DATA.md). The underscore prevents collision with any valid app ID. |

All paths are under the configured API prefix (normally `/api/v1`). Codes and tokens are in request bodies or authorization headers, never URLs, audit payloads or browser storage. Responses are `private, no-store` and timestamps carry UTC offsets. The company service-key catalog adapter exports only app metadata and release observations, not grants, users, business records or sessions.

Each portal catalog installation includes `ui_entrypoint`, projected from its current trusted release's immutable manifest snapshot. The latest registered definition can describe code that has not been deployed, so hosts must use this installation field for iframe routing; code rollback restores the earlier release's route. Only a development installation with no release uses the current definition for its existing unbuilt preview. An untrusted release or unbuilt production installation returns `ui_entrypoint: null` and `launchable: false`, never a fabricated route to another version.

The browser [SDK](../../../../../../packages/app-sdk/README.md) validates exact origin, window source, protocol, installation and request nonce. App servers proxy exchange and identity introspection to their configured platform; third-party cookies and global CORS are not prerequisites. Reconnect starts a fresh handshake. The typed server setting `MIY_INDEPENDENT_APP_PLATFORM_ORIGINS` must list the actual platform browser origins, including a separately hosted portal. Registration rejects these origins as app origins; launch and subsequent session checks also enforce that boundary. The default empty list disables independent installation/session admission. The portal additionally checks the actual browser origin. Deployment must configure the correct external host/scheme and prove distinct portal/app origins in the actual browser.

## Atomic first registration

The portal exposes this create-only flow at `/apps/register`, linked from its app
list. Download `miy-app-registration.json` from a source-connected Workbench
project, sign in to the MIY portal as the intended owner, import the file, and
confirm the app's separate development origin and allowed requested permissions.
The file envelope is limited to **256 KiB**; Workbench's source-manifest reader has
a separate **64 KiB** limit. An exported draft for an existing app cannot overwrite its
registration. The [Workbench procedure](../../../../../../docs/apps/codex-console/README.md#등록-초안-파일로-최초-앱-등록)
owns the manual file handoff. It uses the current MIY login without transferring
that credential to Workbench, weakening COOP, or issuing a new write token.

`POST /independent-apps/bootstrap` accepts `operation_id` (UUID), `definition`,
`source_revision`, the app's separate development `origin`, and optional
`granted_permissions` (default `[]`). The current, non-impersonated MIY owner login
is required. Even an administrator can only create a **personal**, **disabled**
development installation with `selected` audience, the owner as its sole user,
and no groups. Additional policy fields are rejected. The existing definition,
origin, permission-subset, company-control and audit validation is reused; built-in
IDs, official definitions, an existing app ID and another installation's origin
cannot be adopted. Choose an origin operated for this app; this registration does
not contact or attest the ownership/health of that server.

The response is an immutable receipt containing only `operation_id`, `app_id`,
`installation_id`, `definition_digest`, `source_revision` and `created_at`.
`GET /independent-apps/bootstrap/{operation_id}` returns it to the same current
owner; another user, including an administrator, receives 404. Repeating the
same operation and exact canonical input returns the initial receipt, without
restoring a definition or installation that was subsequently edited. Another
operation for the same app is a conflict. No session, delegation, release or
execution status is included in the receipt. The portal labels it as an initial
registration record, not evidence of the installation's current readiness or
deployment status.

Canonical inputs include the validated manifest defaults, source revision,
owner, origin and the fixed installation policy. Object-key order is irrelevant.
`granted_permissions` rejects duplicates and ignores ordering. Arrays inside
`AppDefinition`, including `requested_permissions`, retain the existing manifest
digest semantics: changing their order changes the definition and conflicts on
operation replay. Workbench's raw `source_manifest_digest` is a different hash;
it must not be substituted for the core `definition_digest`. The source revision
is registration metadata and becomes trusted delivery evidence only after the
existing core builder verifies its actual committed bytes.

PostgreSQL commits the definition, company control, disabled installation, both
existing audit records and completed operation in one transaction. Sorted
transaction advisory locks serialize operation/app/origin conflicts; database
unique constraints also protect races with existing owner APIs. Authority is
rechecked after lock waits and after flush. Non-READ-COMMITTED and AUTOCOMMIT
connections are rejected. `stage_definition` and `stage_installation` validate and
flush without committing; their existing public owner API wrappers still commit
as before. The bootstrap adapter rolls all staged resources back on failure.
An adapter-local PostgreSQL `lock_timeout` of five seconds also bounds waits for
advisory/constraint locks. Exact SQLSTATE `55P03` becomes localized HTTP 503;
unrelated database failures are not reclassified. Rollback/commit resets the local
setting, and this does not change the platform's global connection policy.

After a timeout or lost response, retain the same operation ID and payload and
query its receipt. A 404 means no completed receipt is visible, and may occur while
the original transaction is still running; it is not proof that a different
operation is safe. Resuming the same request serializes with the original. There
is no pending-operation workflow, automatic retry, clone, source mutation, build,
service start, preview activation or secret issuance in this endpoint. The portal
keeps only the operation UUID in the URL and freezes the submitted body while its
result is unknown. Reload queries the receipt without submitting again; a manual
retry after reload requires the original draft and matching inputs. Confirmed
input/authority/conflict rejections allow correction while retaining that UUID.
The JSON-file flow keeps Workbench source preparation and portal confirmation
as separate actions. The optional registration authorization below supplies a
separate, narrowly scoped server credential. Delivery delegation, the
operator's runtime/executor configuration, and actual build/deployment remain
subsequent steps.

`independent_bootstrap_20261006` adds only the completed-receipt table after
`official_writer_roles_20261006`. Downgrading it removes receipt history and leaves
definitions, installations and audits intact. Such existing apps cannot then be
adopted by a new operation; preserve the receipt table in backups if replay/status
continuity is needed. This migration is not an application-code rollback.

### Optional Workbench first-registration authorization

`MIY_CODEX_CONSOLE_REGISTRATION_AUDIENCES` is an empty-by-default typed list of
exact Workbench base URLs. Use the actual HTTPS origin plus its configured base
path, without a trailing slash; HTTP is restricted to loopback. Base-path segments
contain only letters, digits, underscores and hyphens, matching Workbench's own
setting. Credentials, query strings, fragments and encoded paths are rejected.
This is a separate opt-in from the existing Workbench launch URL and company app
admission. It does not change the read-only platform API key scope registry,
identity-only SSO, or installation-bound delivery delegations.

All new paths start with `/independent-apps/bootstrap-authorizations`. Current,
non-impersonated MIY login authorizes `POST` with version 1, request UUID, fixed
registration operation UUID, audience, S256 challenge and public policy
(`app_id`, exact development `origin`, `runtime_profile`, requested permission
set). The owner consent fixes personal/create-only registration, a disabled
development installation for that same owner, and **empty granted permissions**.
The server returns a `miyrc_` one-use code for at most 120 seconds; the resulting
registration grant expires at most 300 seconds after consent. Both deadlines are
capped by the source MIY session and exchange does not extend them.

The portal sends only `request_id` and `code` as a form POST to the returned exact
`audience + /api/registration-authorizations/callback`. Neither code, verifier nor
bearer belongs in a URL. Workbench's server calls `POST /exchange` with version,
request ID, audience, code and private verifier. The returned `miyrg_` token is
server-only and authenticates only `POST /{id}/bootstrap` (existing BootstrapInput)
and `GET /{id}/receipt` for the approved operation. `DELETE /{id}` requires the
current owner login; another owner, including an administrator, cannot revoke it.
Reusing a consent request UUID conflicts instead of reissuing a secret. Explicit
reconnection uses a new request UUID/challenge and preserves the operation UUID.

The portal consent route is `/apps/authorize-registration`; its URL carries only
`v=1`, request/operation UUIDs, audience, `code_challenge`, app ID,
`development_origin`, runtime profile and comma-separated requested permissions.
The callback form transport must still be allowed by the portal's configured CSP
`form-action`: a sandboxed same-origin, no-script frame uses its own origin-only
referrer policy without relaxing the parent's CSP/COOP or default referrer policy.

The hash-only authorization row is locked for code exchange and each delegated
request. Source session, active user, impersonation, current Workbench admission,
allowlisted audience, grant expiry/revocation and fixed policy are rechecked at
the bootstrap boundaries before/after its advisory locks and after resource
flush. The initial payload digest and consumption timestamp commit with the
existing definition/installation/audit/receipt transaction; failure rolls them
all back. An already committed same-payload replay remains read-only and does
not mark a newly issued recovery grant as consumed. Requested permissions are
compared as a set while the original manifest array order remains part of its
canonical payload digest.

Grant revocation serializes behind a registration transaction already holding
that grant row; it does not retroactively cancel a committed registration. Source
session/account/admission changes use their existing independent rows and are
rechecked after waits. No submitted external action is being cancelled here:
registration performs only its existing PostgreSQL transaction and never fetches
source URLs, runs code or starts services.

After an exchange response is lost, reconnect explicitly; an unreceived token
cannot be recovered from the hash-only row and the short original deadline
remains. After a bootstrap response is lost, retain the frozen operation/body
and query its receipt or explicitly repeat that exact command. A fresh grant
from the current owner can read the same historical operation after the old
grant/session expires, provided the app ID also matches. Receipt observation
does not overwrite source, installation policy or a newly edited definition.
It does not attest a local checkout or grant execution/deployment authority.

`registration_auth_20261007` follows `official_planner_writer_20261006` and adds
only the authorization table and indexes. Its schema downgrade removes these
temporary authorizations, leaving prior bootstrap receipts and app resources
intact. It is distinct from an image rollback. The real remote native executor
still requires the separately verified confinement profile; this authorization
does not relax that boundary or establish an end-to-end natural-language run.

Local owned PostgreSQL 18.6 verification passed 154 tests across this authority,
existing bootstrap, delivery delegation, app/session APIs, identity-only SSO and
the migration chain. One existing negative case was then strengthened to use two
configured audiences and passed separately; this is not an extra distinct test.
The runs preserved their source inventories and removed their owned containers.
Scoped Ruff, compilation, import architecture, i18n and public env-template/typed
settings checks passed. No existing env, database, service or deployment changed.

### Read-only registration comparison

The existing `GET /api/v1/integrations/apps` metadata projection, protected by
`app-catalog:read`, reports `registration_status_version: 1` on every page,
including empty pages. Independent entries expose nullable
`registered_source_revision` from the current definition. `installed_revision`
retains its separate meaning: the selected production release's commit, or null
when none is installed. Updating only the registered commit also changes the
catalog revision. Built-in entries have no independent registered commit.

Workbench explicitly refreshes the complete, consistent catalog and compares its
definition digest and registered commit with the current validated local source.
Missing/unknown capability, incomplete pagination, stale evidence and failed
reads cannot establish absence or a match. This metadata grants no delivery,
installation, source-write or execution authority; it is not a live health check
or a build attestation. The initial registration receipt remains immutable.

## Owner-only initial development preview settings

After first registration, the existing development installation remains disabled.
The portal can read and change its initial private access settings through
`GET` and `PATCH /independent-apps/{app_id}/installations/{installation_id}/owner-preview`.
Both require a current, non-impersonated **MIY owner login**. A platform admin who
does not own this personal app cannot use this surface. Registration bearers,
Workbench login/metadata keys, app sessions and delivery grants do not authorize
it. The installation must already be development/selected/exactly the owner/no
groups; the endpoint never repairs or expands another audience.

The portal page is `/apps/:appId/installed/:installationId/setup`. Owners can
open it from the registration receipt or their development-installation list.
Workbench's historical receipt can also open it in a new tab at its configured,
validated MIY origin; the URL contains only the app/installation IDs, with no
code, token or query credentials, and MIY still requires its own current login.
The Korean/English screen shows the fixed origin/current policy, makes PATCH an
explicit user action, and uses GET after an unknown response. Its initial-only
explanation distinguishes access configuration from a running server or a
verified deployment; opening this optional flow changes no installation procedure.

`OwnerPreviewOut` supplies the current registered definition digest/source
revision, display name, runtime profile, fixed origin, requested/granted
permissions, installation generation and enabled state, company control and
`can_configure`/`unavailable_reason`. This is a configuration observation, not
runtime health or a deployment receipt. Disabled installations remain visible
to their owner in the catalog, but catalog summaries are not complete audience
documents and must not be reconstructed into the older general installation PUT.

`OwnerPreviewPatch` accepts only `expected_generation`,
`expected_definition_digest`, `expected_source_revision`, `enabled` and a unique
subset of the current requested `granted_permissions`. Origin, environment,
source, ownership, audience, company control, installed release and runtime
references are immutable through this surface. Generation and enabled use
strict JSON integer/boolean validation. A matching CAS with unchanged settings
is a no-op: it does not increase generation or add another change audit. A real
change atomically updates the settings, increments generation (invalidating old
launch codes/app sessions), and audits the installation, before/after values
and consented definition/source snapshot. A stale CAS conflicts even when
another client's resulting settings happen to match.

This bounded UI is for **initial, unreleased settings**, not general deployed
configuration or emergency revocation. A release/runtime reference, a state
outside configured/disabled, pending delivery, app-wide pending/unknown build,
or any still-valid build verification makes it read-only. An operator build
without an installation ID, another installation's build, or an older still-valid
verification can therefore also block this initial-only surface. Terminal
failed/succeeded build jobs without valid verification do not block it. Missing
platform origins, a colliding/invalid app origin or disabled company control also
prevent changes. None of these states is automatically repaired or restarted.

Changes require READ COMMITTED with autocommit off and a transaction-local
five-second lock deadline. The server locks definition then installation,
checks current owner authority before/after waiting and after flush, and compares
the current definition/source/installation generation under those locks. It
does not acquire executor job/deployment locks in the opposite order. Existing
foreign keys also hold new related insertions behind the locked definition or
installation until commit; a late queued deployment retains its own expected
generation check before any activation. This endpoint starts no build, runtime,
data provisioning or deployment and never updates a historical registration
receipt. Session/account revocation is revalidated at these checkpoints; this is
not a global transaction lock on all possible account changes.

On a lost PATCH response, read the same owner-preview URL to display the current
configuration. Do not automatically replay PATCH or attribute the GET snapshot
to a particular lost request. An explicit new edit must use the freshly observed
CAS values. Lock timeouts roll back and return localized HTTP 503
(`independent_apps.preview_busy`); other conflicts use HTTP 409 and the current
GET explains any read-only reason. Unrelated database failures are not relabeled.

Enabling access can admit an owner-hosted development origin; it does not prove
that origin is running or serving the registered Git revision. The PostgreSQL
profile additionally needs a verified installed release and separately prepared
data store before its data gateway works. A successful setting change is not
permission to install an executor or activate production. The existing remote
Docker sandbox policy remains a separate execution constraint.

The 2026-10-07 owned PostgreSQL 18.6 validation passed 63 new owner-preview cases
and 95 existing registration/session/delivery/delegation cases (158 total,
101.85 seconds). It covered current-authority revocation during real lock waits
and after flush, concurrent CAS, lost-response reads, no-op/session invalidation,
the actual FK insertion wait followed by old-generation deployment refusal,
and PostgreSQL permissions without a provisioned release. All 63 recorded Core
input files remained unchanged during that run; its exact owned container was
removed. No shared database, running service or deployment was changed. Evidence:
`.runtime/owner-preview-pg/20261007T004818189270Z/` (local and uncommitted).

## Local development delivery

The core-owned [delivery CLI](../../../../../../scripts/independent-app-delivery.py) implements a local development vertical. Run it only from the platform checkout with operator-owned platform configuration. It must not be installed in app Codex workspaces or given app-user access to Docker/platform database credentials. Workbench's existing service key remains metadata-only; the separate owner delegation below authorizes typed delivery requests.

1. Register the source manifest and its full Git revision using the owner API; configure a private development installation at `http://127.0.0.1:<unprivileged-port>`.
2. The operator's `build` command snapshots that exact commit, checks its registered definition/repository identity, and runs core-selected tests/builds in the constrained container. A UUID identifies the durable build. The builder rejects links, special files, committed credentials, redirected Git metadata and oversized archives; it never executes an app Dockerfile or app commands on the host.
3. Successful core checks create immutable local-image evidence and an `AppRelease`. API callers cannot set `verified_at`, supply a verification boolean or turn their release candidate into a trusted result.
4. The owner submits `POST /independent-apps/{app_id}/deployments` with `request_id`, `installation_id`, `release_id`, `action` (`deploy` or `rollback`), `expected_generation` and `expected_release_id`. Reusing the same ID/payload reads the same intent; another payload conflicts. Rollback can select only an earlier successful release of that installation.
5. The operator's `execute` consumes a queued request. It persists intent before daemon work, holds a database fence against competing recovery, verifies current authority/source/evidence again before switching, and health-checks the candidate before changing ingress. The PostgreSQL profile additionally applies its core-owned, forward-only schema preparation before starting the candidate; missing storage configuration fails closed. Failed candidate health retains the previous release.
6. Loaded core ingress metadata and the actual immutable container image confirm activation. Database cutover increments installation generation and enters `cleanup`; the previous stateless container is removed before success releases the executor slot. Previous artifacts/history remain available for code rollback. A code rollback never downgrades a database schema.

Example command shapes (replace every placeholder with explicitly selected local values):

```bash
apps/api/.venv/bin/python scripts/independent-app-delivery.py build --app-id APP_ID --revision FULL_GIT_SHA --build-id UUID --source /absolute/app-repo --work-root /private/build-scratch --toolchain-image sha256:APPROVED_LOCAL_CORE_IMAGE_ID
apps/api/.venv/bin/python scripts/independent-app-delivery.py build-request --app-id APP_ID --installation-id UUID --build-id UUID --source /absolute/app-repo --work-root /private/build-scratch --toolchain-image sha256:APPROVED_LOCAL_CORE_IMAGE_ID
apps/api/.venv/bin/python scripts/independent-app-delivery.py execute --app-id APP_ID --installation-id UUID --request-id UUID --state-root /private/executor-state --ingress-image sha256:APPROVED_LOCAL_NGINX_IMAGE_ID --platform-origin http://127.0.0.1:4200 --platform-api-origin http://127.0.0.1:8001
apps/api/.venv/bin/python scripts/independent-app-delivery.py status --app-id APP_ID --installation-id UUID --request-id UUID
```

`reconcile` accepts the same options as `execute`; it observes an interrupted request before doing anything else. A timeout or lost response is `unknown`, never success or automatic redeployment. `running`, `unknown` and `cleanup` retain the durable executor reservation. Definitive cleanup releases a failed initial preview reservation. An interrupted build cannot be safely adopted without its complete check evidence: it retains its heavy-build slot for operator reconciliation instead of silently claiming success. JSON status is emitted without source logs or credentials; exit code 0 means `succeeded`, and 2 means queued, failed, unknown or rejected.

The first local profile admits four installations and one heavy build; a separate durable slot allows one deployment transition at a time. Apps use read-only images, non-root identity, dropped capabilities, no-new-privileges, 512 MiB memory, one CPU, 256 PIDs, bounded tmpfs and an internal-only network. No app source checkout, host credential directory or Docker socket is mounted. A core nginx ingress owns the loopback listener and has separate bounded resources. Its narrow internal gateway exposes app session exchange/introspection and, only for the PostgreSQL profile, bounded data CRUD. It cannot proxy arbitrary platform endpoints. App session introspection still enforces audience, grants and resource authorization requirements. Revoked build evidence also invalidates admission for an installed release.

The app uses public `MIY_APP_PLATFORM_ORIGIN` for browser messaging and the core's fixed `MIY_APP_PLATFORM_API_ORIGIN=http://miy-platform-gateway:8081` for server exchange. The ingress upstream must actually be reachable from Docker. A platform bound only to host loopback cannot be reached via `host.docker.internal`; do not broaden the platform listener automatically or claim login works from an HTTP health check. A core-owned reachable HTTPS/API ingress or separately approved network configuration is required for that environment.

The offline builder currently supports an ordinary app Git checkout, React/react-dom/Vite versions already present in the explicitly approved core validation image, vendored SDK and the exact FastAPI/uvicorn/httpx/pydantic-settings profile. It does not resolve/install arbitrary dependencies or attest production images. It packages only the bounded approved source and generated UI output through a core recipe. Source edits remain a distinct sandbox concern; no containerized Codex editing claim follows from a successful build.

The source snapshot verifies the requested SHA-1 commit, every referenced tree and each file against the actual bytes returned by Git, then constructs a deterministic archive from those same verified bytes. Git replacement refs are disabled. A changed object filename or a concurrent object replacement cannot substitute different source after verification; loose and packed objects follow the same check. The snapshot contains literal committed files: `.gitattributes` export-ignore/export-subst and `.git/info/attributes` do not omit or rewrite them. Committed credentials therefore remain rejected even if export-ignore would have hidden them. File executable modes and nested UTF-8 names are retained; links and submodules remain unsupported. Bounds are 1 MiB per commit/tree object, 8 MiB per file, 64 MiB per archive, 4,096 entries, 20 nested directories, and one 60-second object-read budget. The existing final archive safety checks still apply. `source_archive_sha256` records this deterministic snapshot, and the builder source hash changes the build profile; existing evidence is not rewritten or upgraded implicitly. The app-workspace preparation CLI reuses this snapshot boundary.

## Workbench delivery delegation

The MIY owner logs in and calls `POST /independent-apps/{app_id}/installations/{installation_id}/delegations` with an explicit `actions` subset of `read`, `sync`, `build`, `deploy`, `rollback`, and optional `expires_in_seconds` (60–86400). The server permits development installations only and bounds expiry by the original login. The response exposes the new token once; PostgreSQL stores only its hash. Keep this token solely in the Workbench server's typed secret configuration, separate from its metadata service key. It must not enter app repositories, Codex sessions, tool results, observations or browser storage. The owner's `GET` of the same path lists grant metadata, and `DELETE .../{grant_id}` revokes a grant.

The delegated base is `/independent-apps/delegated/{app_id}/installations/{installation_id}`. These endpoints require the separate delegation Bearer, never a service key or ordinary product token:

| Endpoint                | Action and accepted input                                                                                                                                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET /context`          | `read`: current manifest/revision, installation generation/release, allowed actions, up to 50 current verified releases with rollback eligibility, and the current `pending_deployment` (ID, target release, action, queued/running/cleanup/unknown state) or null |
| `POST /sync`            | `sync`: versioned definition and source revision with the same digest/revision CAS as registration                                                                                                                                                                 |
| `POST /builds`          | `build`: UUID `request_id`, full `source_revision`, `definition_digest`; creates a durable queued intent                                                                                                                                                           |
| `GET /builds/{id}`      | `read`: build state and resulting release ID, without source logs or credentials                                                                                                                                                                                   |
| `POST /deployments`     | `deploy` or `rollback`: the existing deployment request contract and current installation CAS                                                                                                                                                                      |
| `GET /deployments/{id}` | `read`: durable request status                                                                                                                                                                                                                                     |

Every call checks the bound app, installation, development environment, actor, original login, current app ownership/role and admission, expiry, explicit action and revocation. Build claim, build verification and runtime cutover check them again after slow work. A generation increment from successful deployment does not force relinking; each new operation still carries current generation/release CAS. `sync` can update code revision, display and entrypoints, but cannot change the grant's repository/directory, ownership, SDK/profile or permissions. Such changes require owner review and a new grant. A stale CAS fails rather than overwriting another update.

The installation can already reference the target release while retirement of its old container is still `cleanup` or `unknown`. `pending_deployment` preserves that unfinished operation; matching the installed release alone is not proof that deployment completed. Continue observing the existing ID rather than creating another request.

`build-request` consumes an existing delegated intent only after checking its app/installation binding and live authority. The source path, toolchain image, daemon access and core credentials are selected by the operator, never accepted by the request API. `execute` consumes a queued deployment in the same way. No background executor service is installed or started automatically: a queued request remains queued until a core consumer runs. The API cannot assert a successful build/deployment or directly invoke arbitrary host commands. An uncertain result remains queryable and is reconciled before any new side effect.

## Optional core queue consumer

`MIY_INDEPENDENT_APP_DELIVERY_TARGETS` is a core-only JSON array, disabled by the default `[]`. Each binding contains `app_id`, `installation_id`, `source_root`, `work_root`, `state_root`, `toolchain_image`, `ingress_image`, `platform_origin` and optional `platform_api_origin`. For example, select actual approved immutable image IDs before configuring this shape:

```json
[
  {
    "app_id": "my-app",
    "installation_id": "00000000-0000-4000-8000-000000000001",
    "source_root": "/srv/miy-apps/my-app",
    "work_root": "/srv/miy-core/builds",
    "state_root": "/srv/miy-core/runtime",
    "toolchain_image": "sha256:APPROVED_64_HEX_IMAGE_ID",
    "ingress_image": "sha256:APPROVED_64_HEX_IMAGE_ID",
    "platform_origin": "http://127.0.0.1:4200",
    "platform_api_origin": "https://core-api.example.test"
  }
]
```

The settings reject duplicate installation IDs, mutable image tags, relative or symlinked roots, source roots overlapping the platform checkout, and any cross-binding overlap between app sources, build scratch and runtime state. Browser origins must also be present in `MIY_INDEPENDENT_APP_PLATFORM_ORIGINS`; both origins reject credentials, paths, queries, fragments and non-loopback HTTP. Operator-selected HTTPS/API routing must be reachable from Docker. The worker does not discover destinations, fetch repository changes, install toolchains, open host listeners or infer credentials. Keep core settings and `0700` scratch/state outside every app workspace and out of the native app execution mounts.

```bash
apps/api/.venv/bin/python scripts/independent-app-delivery.py poll-once
apps/api/.venv/bin/python scripts/independent-app-delivery.py serve --poll-seconds 5
```

Run these commands from the platform checkout with the same protected settings as the core API. `poll-once` chooses at most one eligible development intent, oldest by its last attempt, then calls the existing `build-request`, `execute` or `reconcile` consumer. Selection is not a claim: PostgreSQL claims, capacity slots and the existing fence remain authoritative when two consumers race. Configuration is revalidated before each poll. Only delegated build intents with matching app/installation bindings are eligible; build paths and image IDs always come from the core binding. A pending heavy-build reservation skips the build queue while independently eligible deployment requests can continue.

An interrupted deployment in `running`, `unknown` or `cleanup` with a saved runtime specification is observed through the existing `reconcile` operation under the same request ID. Selection skips rows locked by a live executor. Execute and reconcile also share a request-specific transaction advisory guard on a separate database connection, covering the durable intent and cleanup commit/reacquire windows. A concurrent caller returns current state without daemon work; closing the guard transaction releases ownership. The consumer needs two available PostgreSQL connections for its single active deployment. The reconciler takes its authoritative row lock again, revalidates authority before recording a cutover and finishes only the original request’s cleanup. It never prepares or activates another runtime. Unconfirmed observations retain `unknown` and the reservation. Interrupted builds or deployments without a runtime specification still require operator inspection; their evidence is insufficient for automatic adoption. A confirmed terminal failure also remains terminal; only a new explicitly authorized request can retry it. Deployment capacity deferral remains queued and advances its attempt timestamp, so another queued request can be selected. `idle` and `succeeded` return CLI exit code 0; disabled, queued, failed, rejected and unknown return 2. `serve` validates its checkout and settings before entering the loop, polls every 1–60 seconds, emits bounded status without app output or credentials, and stops after an in-flight operation finishes when it receives SIGINT/SIGTERM. Forced process loss preserves durable running state for inspection. A pre-claim configuration/database error reports `operator_check_required`; a subsequent poll may inspect that still-unexecuted request, but cannot replay one already claimed.

When the selected consumer returns `unknown` with the explicit `operator_check_required` code, the poller records only the attempt timestamp so an unavailable target cannot continually take precedence over another eligible build. It updates the selected request only if its original timestamp, state and slot still match and its row is unlocked. Concurrent claims, terminal states, other consumer results and locked rows remain untouched. This bookkeeping does not change status, reservations, authority or runtime evidence. Failures before a request is selected have no request to update.

The [example user service](../../../../../../ops/independent-apps/independent-app-delivery.service.example) is an inert template. Installing or starting a service is a separate operator action; neither MIY nor Workbench performs it. This consumer supports development settings and installations only. It adds no production execution profile and never replays uncertain external effects. Recovery here means observing the original runtime and completing its bounded cleanup, not rerunning its build or deployment.

## Selected platform files

The optional `files:read-selected` permission lets an independent app ask the MIY host to show a Files picker and read the one file the user explicitly selects. The manifest and installation must both grant it, alongside `identity:read`; existing starter manifests keep their existing requested permissions. Both `web-api-v1` and `web-api-postgres-v1` use the same contract. [SDK and host behavior](../../../../../../platform-redesign/SDK_FILES.md) owns the browser protocol; [Files selected access](../files/SELECTED_ACCESS.md) owns source ACL, object identity and bounded storage reads.

`MIY_INDEPENDENT_APP_FILE_SELECTION_SIGNING_KEY` is empty by default, which disables this capability alone. Configure a separate, non-placeholder secret of at least 32 UTF-8 bytes in protected Core settings; do not reuse a content-grant or development key. Rotation immediately invalidates outstanding selection requests and read grants. `MIY_INDEPENDENT_APP_FILE_SELECTION_STORAGE_REGION` defaults to `us-east-1` and must match the configured object store's signing region. No schema migration, grant database, app credential, automatic retry, or operator setting change is introduced by this feature.

All routes are under `/api/v1/independent-apps/_files`. Context is `{schema_version: 1, installation_id, audience, selection_id}`; the two IDs are UUIDs and audience is the exact installed app origin. Bodies reject unknown fields. A token is an opaque ASCII value up to 4096 characters and belongs in the documented body/header, never a URL or log.

| Route | Caller and request | Result |
| --- | --- | --- |
| `POST /selection-request` | Live app bearer plus context | Context, `selection_request`, `expires_at`, `max_bytes: 10485760` |
| `POST /candidates` | Original MIY login plus context, `selection_request`, optional literal `query` (120 characters), opaque `cursor`, `limit` (1–25) | Context, `items`, `next_cursor`, `incomplete` |
| `POST /authorize-selection` | Original MIY login plus context, `selection_request`, `file_id`, required `expected_version` | Context, `file`, `read_grant`, `expires_at` |
| `GET /content?installation_id=…&audience=…` | Same app bearer plus `X-MIY-Selected-File` header | Whole bytes, `application/octet-stream`, exact `Content-Length`, attachment disposition, `private, no-store`, `nosniff`, `no-referrer` |

File metadata is `{file_id, name, content_type, size_bytes, version}`. `version` is an opaque 64-hex digest of the source-owned object and ACL binding. The host must pass the observed value back on selection; replacement or changed access rejects the request. Empty files are valid. A partial page may have no visible items and still have a cursor or `incomplete: true`; it does not establish that the user has no accessible files.

Selection requests expire within 60 seconds; read grants expire within 120 seconds, capped by both app and original MIY session expiry. Their signatures use distinct purpose/domain prefixes. The internal app token hash in a signed claim is a lookup selector, not a bearer or an API authentication option. Every stage checks the current app session, installation generation, effective release permission, app/Files admission, source MIY session and current source ACL. Host selection additionally requires that exact original MIY login, not merely another login by the same user. The authorization audit records IDs only. Audit waits are followed by a fresh authority/version check before the grant is published.

Read grants support repeated reads within their lifetime and current authority; individual grant revocation is not implemented. Logout, session/install changes, permission/ACL removal, key rotation, source replacement or expiry invalidate them. A proof may be used again only for a new explicit user selection; clients must not silently reselect or retry a failed read. The app server uses fixed configured Core routes and its app bearer; it receives neither the root MIY bearer nor a general content-grant URL. The existing Files content endpoint is unchanged.

Reads buffer at most 10 MiB per file and recheck authority and descriptor after bounded storage I/O before returning bytes. Each Core process admits at most four concurrent selected-file responses through actual ASGI send completion, cancellation or failure, with immediate `503` when full. A 20-second deadline cooperatively cancels awaited work and is also checked with a monotonic clock immediately before each ASGI header/body send. It prevents new byte delivery after synchronous work has exceeded the deadline; it cannot preempt synchronous SQL or a blocking sender. This limits admitted application responses, not exact wall-clock completion, process RSS, transport buffering or client receipt acknowledgement. Authority revoked after the final check cannot retract bytes already handed to the sender. POST bodies are limited to 8 KiB with a 5-second input deadline. These routes require transactional `READ COMMITTED` and use transaction-local 1-second statement/lock timeouts.

Stable failures use existing localized errors: `session_invalid` (`401`); `file_access_invalid` (`403`, including missing/changed source); `file_size_exceeded` (`413`); `file_request_invalid` (`422`, or `413`/`408` for body limits); and `file_picker_unavailable`, `file_query_unavailable`, `file_read_unavailable` (`503`). Codes have the `independent_apps.` prefix. An ASGI send timeout after headers closes/cancels the response instead of attempting a second JSON error response. All feature configuration and validation here is local implementation evidence; no production key, object store or service was changed.

## Production and remaining boundaries

Production installation activation remains rejected. Registry publication, production artifact signatures/provenance, production ingress/secrets, migration-aware rollout, full browser authentication in the actual deployment domains and operator-managed executor service installation require their own completed acceptance evidence. The planner remains `plan_only`; the explicit core CLI is the executor. Runtime deployment timestamps describe observed deployment work, not continuous live health. Historical images and retired installation reservations require explicit operator lifecycle management; no automatic destructive retention policy is installed.

Validation in the checkout:

```bash
apps/api/.venv/bin/python -m pytest apps/api/tests/test_independent_apps.py apps/api/tests/test_independent_app_environment.py apps/api/tests/test_independent_app_builds.py apps/api/tests/test_independent_app_delivery.py apps/api/tests/test_independent_app_runtime.py apps/api/tests/test_alembic_migrations.py -q
MIY_TEST_INDEPENDENT_DOCKER=1 apps/api/.venv/bin/python -m pytest apps/api/tests/test_independent_app_delivery_docker.py -q
node --test packages/app-sdk/src/index.test.mjs
pnpm check:api-contract
pnpm check:api-architecture
```

Native PostgreSQL tests cover one-use exchange races, session/policy revocation, source CAS, verification evidence, request idempotency, failed-health preservation, rollback, capacity, uncertain responses and concurrent recovery fencing. `test_independent_app_delegation.py` checks the live owner grant and core build consumer; `test_independent_app_executor.py` checks typed target boundaries and queue selection without inventing another claim protocol. The Docker runtime tests are explicitly opt-in with `MIY_TEST_INDEPENDENT_DOCKER=1` and locally approved image IDs; their synthetic apps and owned resources are disposable. The combined delivery test builds two actual Git revisions into distinct immutable images, including an owner-delegated build consumed by the real CLI, deploys through the PostgreSQL intent, loses the response after real ingress activation, verifies `unknown` status and no repeated side effect, reconciles the observed image, and rolls back to the earlier artifact with the expected HTTP content. The separate [capacity probe](../../../../../../scripts/smoke-independent-app.py) records actual cgroup limits for four previews and one bounded build. These checks do not establish another server's capacity or production readiness.

The 2026-10-06 snapshot integrity review reproduced two accepted source substitutions in disposable repositories: a changed loose blob under the original object name and a replacement commit selected by `refs/replace`. After the verified-byte snapshot fix, `test_independent_app_builds.py` plus `test_independent_app_workspace.py` passed 42 tests, including replacement before/after the actual read, malformed/hash-invalid objects, size/entry/depth limits, packed objects, deterministic attributes handling, and failed-workspace cleanup. With `MIY_TEST_INDEPENDENT_DOCKER=1`, `test_independent_app_runtime.py` passed 6 tests in 9.02 seconds and the subsequent `test_independent_app_data_docker.py` passed in 18.90 seconds. These actual container checks built two immutable revisions, exercised UI activation/HTTP/retirement/rollback and the data profile's proxy/session/PG note retention across code rollback. The final `test_independent_app_delivery_docker.py` also passed in 22.18 seconds, covering delegated CLI build, durable deployment, actual activation response loss, same-ID reconciliation and rollback HTTP proof. Their owned cleanup passed. API import contracts, i18n, Ruff and formatting checks also passed. No existing service, production database or deployment was changed.
