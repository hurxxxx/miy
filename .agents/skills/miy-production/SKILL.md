---
name: miy-production
description: MIY guarded production inspection, deployment, restart, and rollback from the prod checkout. Excludes promotion and local development.
---

# Production Operations

[Release operations](../../../docs/domains/release/README.md) owns topology and rollback. Production source is GitLab `origin/main`; checkout basename `prod` is an execution guard, not a container naming requirement.

App operations use `scripts/prod-app.sh` through `pnpm app:prod:*`; infra operations use `scripts/infra-stack.sh`. Preserve source, env, migration, revision, local/public smoke, and restoration gates. Direct app Compose mutations bypass these gates and are forbidden.

Read-only entrypoints: `pnpm infra:prod:status`, `pnpm app:prod:status`, `pnpm app:prod:smoke`. Select only the authorized mutating action: `infra:prod:up`, `infra:prod:down`, `app:prod:deploy`, `app:prod:rollback`, or `app:prod:up`.

Default rollback restores the prior image without reversing migrations. Incompatible database/configuration cutovers require the owner's immutable-image and protected-env rollback pair. Workbench has its [own release/service](../../../docs/apps/codex-console/README.md#배포-완료-확인).
