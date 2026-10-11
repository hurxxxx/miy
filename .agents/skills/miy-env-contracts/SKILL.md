---
name: miy-env-contracts
description: MIY typed settings, ignored env-file helpers, and dev/prod runtime identity. Excludes incidental env mentions, secret rotation, and service operations.
---

# Environment Contracts

- [Env files/settings](references/env-files.md) owns typed keys and ignored-file installation.
- [Runtime separation](references/separation.md) owns runtime identity, storage namespaces, ports, and checkout guards.
- [Inventory helper](scripts/env-inventory.sh) and [local-file helper](scripts/local-env-files.sh) inspect/install without printing values.

Browser-visible `VITE_MIY_*` settings cannot contain secrets. Report key names, counts, modes, hashes, and redacted status. Env-file installation does not authorize restarting services. Shared physical services follow [release ownership](../../../docs/domains/release/README.md), with logical data isolation where supported.

Verify changed contracts with `pnpm check:env-contract` and `pnpm check:path-hardcoding`; helper changes also require fixture checks.
