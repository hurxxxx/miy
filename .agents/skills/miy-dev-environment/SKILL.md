---
name: miy-dev-environment
description: MIY local development stack entrypoints and first-run verification. Excludes production operations and env schema changes.
---

# Development Stack

[INSTALL.md](../../../INSTALL.md) owns dependencies, versions, setup, access, and recovery. Preserve existing ignored env values; initialize only a missing target during authorized setup. [The env helper](../miy-env-contracts/scripts/local-env-files.sh) reports status without values.

```bash
pnpm dev:infra:up
pnpm dev
pnpm dev:minimal
pnpm dev:login-smoke
./dev.sh --status
./dev.sh --restart
./dev.sh --stop
```

Select the requested lifecycle action. Server setup uses the guide's browser access and external login checks; browser tooling remains available through its installed CLI. Existing test/CI requirements still apply. Inspect migration drift rather than stamping or deleting state to bypass it.
