# Web Agent Rules

- Start with current UI code/tests plus `docs/agents/ui-components.md` and `docs/product/ui-design-principles.md` when UI behavior changes.
- Existing shell adapters live under `apps/web/src/app-modules/<appId>/`. Official business UI moves to its declared owner in `packages/official-suite-web`; use its public entrypoints and keep compatibility adapters thin. Cross-app access uses manifest, `public-api.ts`, or bootstrap DTO. Independent app frontends follow their own runtime contract.
- Search existing app, shared components, platform helpers, and `packages/ui` before adding UI abstractions.
- Keep authoritative/shared state on the server; browser state may hold only ephemeral presentation state.
- User-facing copy adds aligned `ko-KR` and `en-US`; preserve interpolation variables and accessible names.
- Copy lives in `apps/web/src/platform/i18n/resources.ts` unless an app extension owns it. Use full-sentence keys, pass localized copy into `packages/ui`, and run `pnpm check:i18n` for rendered copy/catalog changes. Logs, identifiers, and fixtures do not automatically require translation.
- Use generated API contracts and existing app-route/directory/time/feedback primitives; never hand-edit generated artifacts.
- Validate keyboard/focus, loading/empty/error/unavailable, narrow viewport, and stale-response behavior for changed flows.
- Consolidate affected Vitest, `pnpm check:web-architecture` and type checks after the requested changes are integrated. Reuse current evidence for unchanged inputs; let required CI own the full suite. Recheck failed or newly affected boundaries after a fix.
