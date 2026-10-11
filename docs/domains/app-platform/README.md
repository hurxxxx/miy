# App Platform Contract

## Source Of Truth

[ADR 0012](../../../adr/0012-company-app-access-without-workspaces.md) owns the breaking
company/users/groups design. One deployment serves one company. There is no product workspace,
workspace membership, implicit default container, workspace route, or workspace override.
Filesystem working directories and package-manager workspaces are unrelated.

`packages/contracts/app-contracts.json` owns app identity, localized `title_translations`, `icon_key`, routes, execution context, resource scope,
launcher placement, and the ordered `official_app_ids` membership; its schema validates the source and `pnpm generate:app-contracts` generates
both TypeScript and Python projections. Generated files are never edited manually. Display categories
such as `ai`, `collaboration`, and `business` are not executable app identities.

Optional `management` metadata in that same contract provides a short purpose, capability keywords,
repository-relative `source_paths`, and `release_unit` for MIY Workbench. Paths must remain inside the
checkout. Every registration is discoverable without this metadata. Workbench reports unavailable
source and release configuration explicitly; absent metadata never implies a `miy-app` release.
The platform shell and Workbench use the same manifest labels and shared UI icon registry.
This metadata grants no execution or resource access.
Leaf apps share the `miy-app` Web/API/Worker release. The standalone `codex-console` identity retains
its technical ID and uses the separate `miy-workbench` release while displaying **MIY Workbench**.
An app is not an independently deployable service merely because it has a catalog entry.

The [official suite composition](../../../apps/official-suite/README.md) now owns a separate
local UI entry/build artifact. The shared `OFFICIAL_APP_IDS` contract owns the 12-app membership
and order; both roots consume one legacy public-module adapter. This stage still bridges to
existing web public app entries, shell, auth client and
toolchain; the current `miy-app` API/worker/DB writer and release remain authoritative. Its
ownership manifest describes the planned source boundary and does not activate another writer.
The [transition design](../../../platform-redesign/OFFICIAL_APPS.md) owns the remaining runtime
delegation, app-ID ownership, source ACL and queue/outbox cutover work.

The [official API artifact](../../../apps/official-suite/api/README.md) now uses separately owned
platform/official router compositions with the same handlers and authorization dependencies.
The legacy API preserves their combined endpoint set and order. The two split ASGI profiles are
inactive: business HTTP/WS is rejected, health identifies inactivity and readiness returns 503.
The worker uses one source/Beat ownership catalog with its existing single bootstrap. Activation
depends on the [writer cutover contract](../../../platform-redesign/OFFICIAL_API_CUTOVER.md),
including implicit auth session writes and source projection/outbox dependencies.

[App management projections](../integrations/README.md#앱-관리-조회) own external read scopes and
installed revision/usage DTOs. [MIY Workbench](../../apps/codex-console/README.md) owns projects,
maintenance records and development usage in its independent owner-operated store. App business
configuration and company app admission remain in their existing product administration surfaces.

## Routes And Bootstrap

Browser routes are `/apps/:appId/...`; the neutral launcher is `/`. APIs are `/api/v1/...`, with one
account bootstrap at `GET /api/v1/apps/bootstrap`. Old paths and route redirects are unsupported.
Use `buildAppHref` / `build_app_href` and generated routes. A URL or app pin never authorizes access.

### Independent app hosting

The portal also consumes the authenticated `/api/v1/independent-apps/catalog` projection.
Its definitions and installations are owned by the [independent app service](../../../apps/api/src/miy_api/domains/independent_apps/README.md), not compiled leaf imports.
The launcher lists the current user's `launchable` installations with the definition's localized
name and icon. It reads every page under one catalog revision; an incomplete or failed query is
shown as an error. Owner visibility of an installation is not launch permission.

`/apps/:appId/installed/:installationId` is the generic portal host. It has no app-specific route
registration or official-app sidebar. The iframe uses the installation's exact, separate origin,
`allow-scripts allow-same-origin allow-forms allow-downloads`, and no referrer. Same-origin hosting
is rejected. App code cannot navigate the portal or inherit its login token. The host and
[browser SDK](../../../packages/app-sdk/README.md) bind the versioned handshake to the installation,
origin, window source and request UUID. A PKCE-bound one-time launch code is delivered by
`postMessage` to the exact origin, never in a URL. The app backend performs exchange and identity
validation; third-party cookies are unnecessary.

Frame reload, installation generation changes, session changes, access withdrawal and unmount
cancel pending launch responses. The catalog refreshes on focus and every 30 seconds while visible;
the server checks current admission again for launch and every app identity request. Connection
failure is visible and the user can reload or open the standalone app.

Standalone apps open the same authenticated host route with `?connect=popup`; this host binds the
handshake to the app's opener window. The app's configured platform origin remains authoritative.
Compatible cross-origin opener policies are required for this popup path; deployments must verify
their actual proxy headers. The implementation does not relax existing COOP or CSP headers.
Chromium regressions exercise the real portal/SDK across separate origins in `Asia/Seoul`, including
iframe and popup login, absent platform credentials at the app, and access withdrawal. API fixtures
are synthetic; production origins, proxy policy and production app artifacts require deployment verification.

## Core And App Authorization

Core owns accounts, employment assignments, live company groups with HR attributes, app admission and directory selectors.
[Organization](../organization/README.md) owns group derivation and lifecycle. Apps own business
containers, roles, sharing tables, approval and ownership transitions. PMS spaces and memberships
are PMS resources; group binding delegates a PMS role without making the group a space.

`platform_admin` authorizes platform administration and company business read access. It does not
implicitly grant business writes, PMS ownership, or access to personal mail, calendars, messages,
AI sessions/artifacts and personal authoring. The account impersonation endpoint is removed. The
last active platform administrator cannot be demoted, blocked, deactivated or deleted.

Personal-content restrictions govern application authorization. Account administrators still control
credential recovery, and database/storage operators remain trusted infrastructure administrators;
this model does not provide cryptographic confidentiality against those authorities. Password resets
are audited and revoke existing sessions. Temporary-password accounts may only inspect their account,
change the password, or log out until the password change succeeds; app APIs, WebSockets and queued
user work enforce this restriction on the server.

PMS owners are explicit users; groups may be viewer, member or admin. Parent-row locking serializes
member/group changes and owner checks. Group membership or organization-head metadata cannot create
an owner. Creating a folder or list inside an existing space preserves the actor's current role;
it never materializes group-derived access as a direct membership. Only creation of a new space
assigns its creator ownership. Each app resolves resource rights from current source state after
checking app admission.

## App Admission

An active, unblocked account must satisfy company app enablement, registered feature/system-role
requirements, and the app audience. Policy is `all` or `selected`; selected direct users and live
HR-source/local-source groups are combined with OR. Missing configuration and an empty selected audience
deny ordinary users. Platform administrators bypass only audience selection; master disablement and
feature requirements still apply. No resource share or public link bypasses this gate.

`/admin/apps/access` edits `/api/v1/admin/apps/{app_id}/access-policy` atomically. Account, organization,
group and policy changes record audit evidence and invalidate principal projections. Inactive assignment
records may be retained for review and later reactivation; they confer no current authority.
Group membership changes invalidate users gaining or losing membership, and group activation changes
invalidate its members. Group creation and descriptive edits do not invalidate unrelated user sessions.

App admission applies to registered executable apps. Core personal communication (DM), company
announcements, directory selectors, notifications and calendar aggregation remain authenticated
platform capabilities rather than independently selectable apps. Each retains its source-owned
permissions: DM participation, administrator-only announcement writes, and source-filtered calendar
and notification projections. Their core placement does not grant access to a disabled source app.

## Content Ownership And Sharing

Standalone Docs, Whiteboard, Bento, Diagrams and uploaded files begin personal. User/group sharing
preserves personal ownership. Publishing to a company or PMS context requires source sharing authority,
explicit company-admin-read acknowledgment and a same-transaction audit record. Company ownership is
irreversible; unlinking or revoking an audience does not restore personal ownership.
The same acknowledgment is required when creating Docs from a PMS sidebar/task description or
creating/linking a personal Whiteboard from PMS and Meeting. Cancellation sends no publication request
and keeps a resource picker open. Reordering a PMS space must only change documents managed by the
actor whose primary target is that exact space; task references and other primary targets are excluded.

Docs/Whiteboard `company_visible` separately grants read access to everyone admitted to that app.
Project publication alone leaves this flag false. Removing company-wide visibility preserves project,
user/group grants and company ownership; the UI must not imply that all those grants were removed.
Company administrators retain read access, while mutations require app-owned resource rights.
Company publication and the primary project connection are independent controls. Changing the primary
connection preserves other project targets; removing it does not revoke other sharing grants.
The personal-only summary requires personal ownership with no user/group, active-link or source-target
sharing. A stored group grant remains a sharing configuration even while that group is inactive.
Bento/Diagrams use company ownership for publication and cannot offer a return to personal ownership.

A supplied shared-link token bounds access to that exact active link and its read/edit level, including
for the owner. Invalid links cannot fall back to stronger owner/group/target rights, and links never
permit sharing administration. Current source ACL is required before REST, search, RAG, notification,
media or collaboration disclosure; partitions and saved projections only narrow candidates.

## Realtime Authorization

The common WebSocket checks the current account and session before each incoming or outgoing
message. Resource subscriptions additionally check current app admission and source rights at
subscription and immediately before sending content. Queued authorization is not reusable authority.
A supplied link remains bound to the exact current token and its access level.
Bindings are keyed by topic, resource ID and the exact share token (or direct-access null),
including client reference counts and unsubscribe. A second lens cannot replace the first binding.

Docs uses its existing `docs.pages` subscription for `docs.access.changed` with only `doc_id`;
Whiteboard uses `whiteboard.access` for `whiteboard.access.changed` with only `whiteboard_id`.
User/group/company/link/target changes and deletion publish after commit to that resource's existing
observers. They do not broadcast account invalidation to unrelated users. A revoked observer receives
one ID-only invalidation and loses the server subscription, including already queued source frames.
No title, content, token or actor is included. Rejected known-resource subscriptions return the same
requested-ID-only invalidation so a read followed by a raced subscription denial cannot retain a
stale open view.

Views discard the previous resource/editor state and ignore obsolete in-flight responses before
refetching current rights. Reconnects refetch canonical HTTP state because Redis live events are
at-most-once. Server source checks remain authoritative if a client ignores invalidation. Docs and
Whiteboard Yjs transport checks the current session, app and source edit rights on every received
frame before room mutation and every outgoing frame after acquiring the send lock; the periodic
monitor also closes idle revoked connections.

Docs and Whiteboard snapshot workers share one process-wide admission lease across hubs and event
loops. Workers stay parallel, including Whiteboard's existing four-worker limit, and hold this lease
through transaction outcome and Session cleanup. Once a native room disposal waits, new workers
await admission before opening a Session or starting their SQL budget. Disposal drains active workers
without blocking the event loop, then releases native state and runs its explicit full collection on
the room's owner thread. Cancellation joins that owned disposal before propagating. This coordinates
the platform's explicit room-disposal `gc.collect()` only; automatic or third-party GC is not disabled
or covered by this exclusion. SQL budgets, identity checks and retry/unknown-outcome policy stay fixed.
Final Docs and Whiteboard disposal joins snapshot admission and persistence before releasing native
state, even after caller cancellation. Admission waits do not consume the non-SQL cleanup timeout;
that timeout still bounds client/relay/room cleanup, and the SQL budget begins after admission.
Docs and Whiteboard ignore only the exact empty Yjs delta emitted by native read transactions, so
snapshot encoding cannot cancel its own scheduled save. Delete-only updates still save and relay.

Common and collaborative WebSockets authenticate with the first `auth` message. URL `token`
authentication is rejected, including a valid or empty query token. Session credentials must not
appear in socket URLs. Docs and Whiteboard share `createAuthenticatedCollabProvider` in the UI
editor package. It uses the [official y-websocket provider API](https://docs.yjs.dev/ecosystem/connection-provider/y-websocket):
`connect: false`, a `status` listener registered before connecting, and the public `ws` socket.
Pinned y-websocket 3.0.0 emits `connected` synchronously before initial sync (`src/y-websocket.js`,
lines 196–210), so each connection/reconnection sends authentication before binary Yjs frames.
An installed-provider regression checks this order. Reassess that ordering when upgrading the
provider; no WebSocket monkey patch or second reconnect lifecycle is used. `disableBc: true`
prevents BroadcastChannel from bypassing server authorization between browser tabs.

Per-user events also retain source authorization: DM rebuilds conversations/messages from current
participation and the current join-history window. A removed participant receives only the existing
conversation-removed ID; rejoining cannot recover queued pre-join messages. Notifications rebuild
the recipient/source-visible row and unread count at delivery. If the row is no longer visible,
the event contains `notification: null` and the current count, without the old title/body/action URL.

## App Bar Presentation

- Static `launcher.placement` declares whether a leaf is fixed, a personal tool, or eligible for a
  company category. `launcher.pinned_by_default` supplies only the initial personal pin default.
- `platform_app_bar_categories` and `platform_app_bar_category_apps` own company category title,
  icon, order, and app membership. Admin manages them through `/api/v1/admin/app-bar-categories`;
  bootstrap filters every item through the current user's executable app catalog.
- `users.app_bar_layout.pinned_app_ids` owns at most eight personal pins. On reads, the server
  removes unknown, fixed, personal-tool, and duplicate IDs; a missing or malformed list falls back
  to compiled pinned defaults. Preference writes reject unknown IDs.
- Category assignment, pinning, ordering, and hiding never create an app identity or authorize a
  route, API, worker, search result, notification, or AI capability.

## Standalone Launcher Destinations

A registered leaf may declare `launcher.url_setting`. Bootstrap reads that typed setting only after
normal company, role and audience admission, and exposes it as `launch_url`. Unconfigured consoles
remain unavailable through their feature predicate. Browser launcher, desktop personal tools and
mobile navigation open these destinations with `target="_blank"` and `rel="noopener noreferrer"`.
The registered `/apps/:appId` entry remains an admitted fallback with an explicit open link.
No application token is forwarded. Codex Console is the narrow exception: after normal app admission,
miy issues a 60-second, purpose-bound code in the new window's URL fragment. The console removes the
fragment, exchanges the code once from its server, and creates its own session. miy rechecks the source
session and current app admission during exchange. The exchange returns only the stable miy user UUID;
the console creates a session only when it matches the owner UUID configured for that exact issuer.
Other destinations own their authentication and resource access.
Codex Console installation and its independent subscription runtime are owned by
[Codex Console](../../apps/codex-console/README.md).

## Backend Registration

- A domain exports one immutable leaf registration from
  `apps/api/src/miy_api/domains/<domain>/app_catalog.py`.
- `apps/api/src/miy_api/domains/auth/app_catalog.py` is the explicit composition root.
- `compile_app_registry()` rejects duplicate identity/routes/nav, invalid ownership, and inconsistent route metadata.
- Bootstrap, route/API gates, admin controls, AI discovery/execution, search, and background work consume compiled identity plus runtime availability.
- Executable app-owned user work rechecks the current actor's app admission after claiming the job,
  before resolving providers and again after external I/O before mutating app data. This includes
  account state and live user/group audience grants, not just the company master switch.
  Mail sync terminates revoked jobs as cancelled without retrying or applying a fetched response.
  A disabled job pauses or cancels according to that queue's
  terminal-state contract. Compensating cleanup may remove orphaned/expired storage after
  disablement but must not publish new user-visible app state.
- Migration-only app ID lists may exist inside Alembic migrations; runtime allowlists outside the registry are forbidden.

## Frontend Registration

- Hosted app runtime adapters stay under `apps/web/src/app-modules/<appId>/`. Official business manifest/help metadata and the Diagrams UI/API implementation are owned by `packages/official-suite-web`; their old web paths are compatibility re-exports of that public library. Other hosted app views remain in the web tree.
- Each leaf exports an `AppModuleManifest` and owns its routes, submenu, and extension registrations.
- An app with no submenu entries returns an empty navigation projection; the platform never invents a root item.
- Settings/admin is a shell-owned navigation surface, not an executable app identity or availability target.
- The shell composition root imports leaf registrations explicitly and derives route, App Bar, document title, mobile navigation, and background projections.
- Help guides follow the same composition boundary: roots select public leaf `HelpGuide` metadata for both `helpGuides` (modal) and `helpRoutes` (direct routes). The shared renderer has no implicit business-app guides; each registration owns its route, source, translation keys and optional locale source resolver. Help visibility does not grant app or resource access.
- `platform-web` owns the actual shared browser AuthContext, HTTP client and user time implementation. The existing platform AuthProvider retains login/logout/bootstrap/access-refresh lifecycle; both roots initialize the same i18next singleton before use. See [browser platform ownership](../../../packages/platform-web/README.md).
- `core-web/navigation-types` and `core-web/help-guide` own the shared shell metadata contracts. These shared contracts and the official metadata library cannot import application roots; the architecture check covers this direction and cycles across both UI compositions.
- All app routes consume the same current account bootstrap. App-owned resource identifiers remain in app paths.
- User-facing copy keeps `ko-KR` and `en-US` catalogs aligned.

Cross-app authenticated byte delivery follows [Content Access](../content-access/README.md). Global
source events follow [Notifications](../notifications/README.md); notification rows never replace
source authorization.

## Keyword Search

Participating apps provide an app-owned `SearchEntityAdapter`, explicit composition in
`apps/api/src/miy_api/domains/search/default_entity_adapters.py`, lifecycle projection
hooks, source ACL, and disabled/empty/missing-index tests. Search results use the canonical generated
browser route and recheck source access. Retrieval partition is candidate scope, not authorization.

## Change Checklist

- update the source app contract and regenerate both language projections
- update backend leaf registration, route/API gate, admin/runtime availability, and focused tests
- update frontend manifest, app-first routes, submenu, launcher projection, and i18n
- update search, notification, share, worker, and AI links/capabilities owned by the app
- regenerate OpenAPI/client when the API contract changes
- add Alembic migration for persisted schema changes
- verify missing/disabled configuration, selected user/group audiences, inactive principals, private/shared/company resources, and revocation cases

## Checks

```bash
pnpm check:app-contracts
pnpm check:web-architecture
pnpm nx typecheck web
pnpm check:api-architecture
pnpm check:api-contract
pnpm check:i18n
pnpm check:alembic-graph
pnpm test:alembic-graph
(cd apps/api && uv run --python 3.12 --group dev python -m pytest tests/test_app_routes.py tests/test_app_availability.py tests/test_apps_launch_catalog.py tests/test_app_registry.py tests/test_company_groups.py tests/test_company_content_boundaries.py -q)
```

### Revoked realtime sessions

The server closes a revoked user session before sending another realtime payload. Authorization close
codes (1008, 4401, 4403) therefore trigger the existing client account-access refresh boundary: protected
content becomes inert/hidden while current identity is fetched, and denial clears the session. Ordinary
network failures retain reconnect behavior; a policy close is not an unbounded reconnect trigger.
Account suspension and login blocking end existing sessions; reactivation requires a fresh login.
