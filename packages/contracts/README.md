# Shared Contracts

Use this package only for contracts consumed by two or more runtimes/apps.

Current exports:

- `@miy/contracts`
- `@miy/contracts/api`
- `@miy/contracts/app-contracts`
- `@miy/contracts/app-routes`
- `@miy/contracts/auth`
- `@miy/contracts/dm`
- `@miy/contracts/notifications`
- `@miy/contracts/miy-desktop-update-feed`
- `@miy/contracts/miy-desktop-update-feed.manifest.json`
- `@miy/contracts/independent-app.schema.json`
- `@miy/contracts/openapi`
- `@miy/contracts/realtime`

`app-contracts` is generated from `packages/contracts/app-contracts.json`; `app-routes` is the only
shared browser-route builder/parser contract. Regenerate both runtime projections with
`pnpm generate:app-contracts`. OpenAPI types are generated with `pnpm generate:api-client`.
Auth access-invalidation event types and reasons are generated for TypeScript and Python from
`packages/contracts/auth-realtime-contract.json`; run `pnpm generate:auth-realtime-contract` and
verify with `pnpm check:auth-realtime-contract`.

Keep app transport, auth tokens, Electron IPC, and adapter details in owning apps. Promote only shared path/query/payload invariants.

`independent-app.schema.json` projects the versioned Python `AppDefinition` wire contract. Regenerate/check it with `scripts/generate-independent-app-schema.py` using the API environment; the same command maintains the standalone Workbench's bundled schema. Definitions are validated source metadata, not installation or permission authority. See the [independent app owner contract](../../apps/api/src/miy_api/domains/independent_apps/README.md).

## Publish

Publish to the GitLab npm Package Registry only after explicit publication
authorization under the [Git delivery rules](../../AGENTS.md#git-and-delivery).
From the repository root, read the tag version from the package metadata so it
matches the package being published. Preparing or merging a version change alone
does not publish the package.

```bash
contracts_version="$(node -p "require('./packages/contracts/package.json').version")"
git tag "contracts-v${contracts_version}"
git push origin "contracts-v${contracts_version}"
```
