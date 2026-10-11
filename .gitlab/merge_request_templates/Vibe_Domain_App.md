<!-- miy:vibe-app-contract:v1 -->

# Vibe Domain App

Under 2,700 chars. Link logs; explain N/A.

## Contract Map

- Outcome/non-goals; scaffold/Core: <!-- miy:field:contract-outcome --> REPLACE_ME
- App/owner/route/execution/resource scope and runtime availability; data/RBAC: <!-- miy:field:contract-boundaries --> REPLACE_ME
- API/UI/i18n/a11y; file/network: <!-- miy:field:contract-interfaces --> REPLACE_ME
- AI/data/caps; worker; migration/compat: <!-- miy:field:contract-runtime --> REPLACE_ME
- Search (`none - reason` or `company - evidence`): <!-- miy:field:company-keyword-search --> REPLACE_ME

- [ ] <!-- miy:check:scaffold --> Scaffold/Core ready.
- [ ] <!-- miy:check:app-owned-surface --> App-only; no guard bypass.
- [ ] <!-- miy:check:target --> Target follows root `AGENTS.md`.

## Data, Authorization, And Safety

- [ ] <!-- miy:check:authorization --> Server auth/RBAC negatives.
- [ ] <!-- miy:check:transaction --> Transaction/retry/concurrency/cleanup.
- [ ] <!-- miy:check:file-network --> File/URL security/caps.
- [ ] <!-- miy:check:ai --> Registered workload/common interface/caps/budget/audit/data/approval; no direct provider call, or N/A.
- [ ] <!-- miy:check:worker --> Worker import/queue/retry/Linux.
- [ ] <!-- miy:check:compatibility --> Data/routes/workflows compatible.
- [ ] <!-- miy:check:company-keyword-search --> Registry/ACL/index evidence, or `none` reason.

Evidence or N/A reasons: <!-- miy:field:safety-evidence --> REPLACE_ME

## Verification Evidence

- Pipeline diff-base SHA: <!-- miy:field:target-state --> REPLACE_ME
- Source SHA: <!-- miy:field:source-sha --> REPLACE_ME
- Checks/CI/negatives: <!-- miy:field:verification --> REPLACE_ME

- [ ] <!-- miy:check:merge-result --> Latest diff/merge reviewed.
- [ ] <!-- miy:check:scope-clean --> Scope clean; no workaround.
- [ ] <!-- miy:check:affected-checks --> Affected checks ran on source SHA.

## Independent Review

- [ ] <!-- miy:check:independent-review --> MR review/reviewer ran.
- [ ] <!-- miy:check:review-freshness --> SHA/base changes rechecked.
- [ ] <!-- miy:check:remaining-risks --> Blockers cleared; risks below.

Remaining risks / intentionally unverified: <!-- miy:field:remaining-risks --> REPLACE_ME
