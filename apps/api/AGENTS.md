# API Agent Rules

- Start with current API code/tests and the closest owning domain document; read accepted ADRs only for touched contracts.
- Routers in this platform API service use `miy_api.api_registry`, with domain behavior in application/service layers. Independent app APIs follow their own runtime contract.
- Enforce actor, declared execution identity, current company app admission, and source-owned resource ACL on the server.
- Product workspaces are removed under ADR 0012. App-local spaces and groups never become a global execution container.
- API/OpenAPI changes must update response models and regenerate the client when `pnpm check:api-contract` requires it.
- Platform ORM schema changes require an Alembic migration from current head; do not use `create_all`, hand SQL compatibility, `stamp`, or destructive repair. Independent app data profiles use their [core-owned versioned migrations and checksum journal](src/miy_api/domains/independent_apps/DATA.md); app-authored SQL cannot change that schema.
- AI, retrieval, and external file/URL changes follow the root boundaries and their owner ADRs/docs.
- Rendered API errors use the existing localized message contract; preserve interpolation and locale parity. Developer logs and identifiers are not product translations. Run `pnpm check:api-i18n` for message changes.
- Consolidate affected pytest, `pnpm check:api-architecture`, API shape and required Alembic checks after the requested changes are integrated. Reuse current evidence for unchanged inputs; let required CI own the full suite. Recheck failed or newly affected boundaries after a fix.
