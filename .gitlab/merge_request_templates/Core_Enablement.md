<!-- miy:core-enablement:v1 -->

# Core Enablement

Keep this description below 2,700 characters. Link logs and owning decisions.

## Enablement Contract

- Outcome/non-goals: <!-- miy:field:outcome --> REPLACE_ME
- Protected surfaces/owners; LLM workload IDs/adapter/external-data policy/output caps or N/A: <!-- miy:field:protected-surfaces --> REPLACE_ME
- App-owned boundary after merge: <!-- miy:field:app-boundary --> REPLACE_ME
- Activation owner/MR/condition: <!-- miy:field:activation --> REPLACE_ME
- Compatibility/rollback: <!-- miy:field:compatibility --> REPLACE_ME
- Company search (`none - reason` or `company - required evidence`): <!-- miy:field:company-keyword-search --> REPLACE_ME

- [ ] <!-- miy:check:independent-deployable --> Scaffold is independently deployable.
- [ ] <!-- miy:check:hidden-default --> Incomplete app stays hidden/disabled/unscheduled.
- [ ] <!-- miy:check:extension-contracts --> Registry/API/RBAC/worker/AI contracts tested; independently configurable LLM functions have registered workloads, output caps, audit, common interface, and direct-call guard evidence.
- [ ] <!-- miy:check:activation-owner --> Activation ownership is explicit.
- [ ] <!-- miy:check:company-keyword-search --> Backend registry is authoritative; app availability, source ACL, empty/missing-index, backfill, smoke, and rollback evidence are recorded, or `none` has a reason.

## Verification Evidence

- Pipeline diff-base SHA: <!-- miy:field:target-state --> REPLACE_ME
- Source SHA: <!-- miy:field:source-sha --> REPLACE_ME
- Checks/CI links and negative scenarios: <!-- miy:field:verification --> REPLACE_ME

- [ ] <!-- miy:check:merge-result --> Latest diff/merge result reviewed.
- [ ] <!-- miy:check:affected-checks --> Affected checks ran on source SHA.

## Core Review

- [ ] <!-- miy:check:core-review --> Core owner reviewed protected composition changes.

Remaining risks / intentionally unverified: <!-- miy:field:remaining-risks --> REPLACE_ME
