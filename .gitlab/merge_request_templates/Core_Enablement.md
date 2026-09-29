<!-- mty:core-enablement:v1 -->

# Core Enablement

Keep this description below 2,700 characters. Link logs and owning decisions.

## Enablement Contract

- Outcome/non-goals: <!-- mty:field:outcome --> REPLACE_ME
- Protected surfaces/owners; LLM workload IDs/adapter/external-data policy/output caps or N/A: <!-- mty:field:protected-surfaces --> REPLACE_ME
- App-owned boundary after merge: <!-- mty:field:app-boundary --> REPLACE_ME
- Activation owner/MR/condition: <!-- mty:field:activation --> REPLACE_ME
- Compatibility/rollback: <!-- mty:field:compatibility --> REPLACE_ME
- Company search (`none - reason` or `company - required evidence`): <!-- mty:field:company-keyword-search --> REPLACE_ME

- [ ] <!-- mty:check:independent-deployable --> Scaffold is independently deployable.
- [ ] <!-- mty:check:hidden-default --> Incomplete app stays hidden/disabled/unscheduled.
- [ ] <!-- mty:check:extension-contracts --> Registry/API/RBAC/worker/AI contracts tested; independently configurable LLM functions have registered workloads, output caps, audit, common interface, and direct-call guard evidence.
- [ ] <!-- mty:check:activation-owner --> Activation ownership is explicit.
- [ ] <!-- mty:check:company-keyword-search --> Backend registry is authoritative; app availability, source ACL, empty/missing-index, backfill, smoke, and rollback evidence are recorded, or `none` has a reason.

## Verification Evidence

- Pipeline diff-base SHA: <!-- mty:field:target-state --> REPLACE_ME
- Source SHA: <!-- mty:field:source-sha --> REPLACE_ME
- Checks/CI links and negative scenarios: <!-- mty:field:verification --> REPLACE_ME

- [ ] <!-- mty:check:merge-result --> Latest diff/merge result reviewed.
- [ ] <!-- mty:check:affected-checks --> Affected checks ran on source SHA.

## Core Review

- [ ] <!-- mty:check:core-review --> Core owner reviewed protected composition changes.

Remaining risks / intentionally unverified: <!-- mty:field:remaining-risks --> REPLACE_ME
