<!-- mty:vibe-app-contract:v1 -->

# Vibe Domain App

Under 2,700 chars. Link logs; explain N/A.

## Contract Map

- Outcome/non-goals; scaffold/Core: <!-- mty:field:contract-outcome --> REPLACE_ME
- App/owner/route/execution/resource scope and runtime availability; data/RBAC: <!-- mty:field:contract-boundaries --> REPLACE_ME
- API/UI/i18n/a11y; file/network: <!-- mty:field:contract-interfaces --> REPLACE_ME
- AI/data/caps; worker; migration/compat: <!-- mty:field:contract-runtime --> REPLACE_ME
- Search (`none - reason` or `company - evidence`): <!-- mty:field:company-keyword-search --> REPLACE_ME

- [ ] <!-- mty:check:scaffold --> Scaffold/Core ready.
- [ ] <!-- mty:check:app-owned-surface --> App-only; no guard bypass.
- [ ] <!-- mty:check:target --> Target follows root `AGENTS.md`.

## Data, Authorization, And Safety

- [ ] <!-- mty:check:authorization --> Server auth/RBAC negatives.
- [ ] <!-- mty:check:transaction --> Transaction/retry/concurrency/cleanup.
- [ ] <!-- mty:check:file-network --> File/URL security/caps.
- [ ] <!-- mty:check:ai --> Registered workload/common interface/caps/budget/audit/data/approval; no direct provider call, or N/A.
- [ ] <!-- mty:check:worker --> Worker import/queue/retry/Linux.
- [ ] <!-- mty:check:compatibility --> Data/routes/workflows compatible.
- [ ] <!-- mty:check:company-keyword-search --> Registry/ACL/index evidence, or `none` reason.

Evidence or N/A reasons: <!-- mty:field:safety-evidence --> REPLACE_ME

## Verification Evidence

- Pipeline diff-base SHA: <!-- mty:field:target-state --> REPLACE_ME
- Source SHA: <!-- mty:field:source-sha --> REPLACE_ME
- Checks/CI/negatives: <!-- mty:field:verification --> REPLACE_ME

- [ ] <!-- mty:check:merge-result --> Latest diff/merge reviewed.
- [ ] <!-- mty:check:scope-clean --> Scope clean; no workaround.
- [ ] <!-- mty:check:affected-checks --> Affected checks ran on source SHA.

## Independent Review

- [ ] <!-- mty:check:independent-review --> MR review/reviewer ran.
- [ ] <!-- mty:check:review-freshness --> SHA/base changes rechecked.
- [ ] <!-- mty:check:remaining-risks --> Blockers cleared; risks below.

Remaining risks / intentionally unverified: <!-- mty:field:remaining-risks --> REPLACE_ME
