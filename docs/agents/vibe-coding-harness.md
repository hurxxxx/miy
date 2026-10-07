# Development Validation and Agent Contracts

Root [AGENTS.md](../../AGENTS.md) owns authority and critical platform boundaries. This document maps validation and native agent integration; it does not prescribe a universal development procedure. Current redesign decisions and implementation evidence are in [platform-redesign](../../platform-redesign/README.md).

## Router

| Change             | Owner                                             | Minimum checks                                                          |
| ------------------ | ------------------------------------------------- | ----------------------------------------------------------------------- |
| Docs/skills/policy | current file owner                                | `git diff --check`; `pnpm check:skills` if skills/policy                |
| GitLab CI/harness  | harness owner                                     | `pnpm check:gitlab-pipeline`, `pnpm ci:harness`                         |
| Translation        | i18n catalog                                      | `pnpm check:i18n`                                                       |
| Env/runtime        | env settings/compose/scripts                      | `pnpm check:env-contract`, `pnpm check:path-hardcoding`                 |
| Web app-local      | app module/UI owner                               | `pnpm check:web-architecture`, `pnpm nx typecheck web`, focused Vitest  |
| Web test fixtures  | generated DTO / test owner                        | `pnpm exec tsc -p apps/web/tsconfig.spec.json --noEmit`, focused Vitest |
| API/domain         | domain router/service/tests                       | `pnpm check:api-architecture`, focused pytest                           |
| OpenAPI/generated  | API contract                                      | `pnpm check:api-contract`; generate client when required                |
| Worker             | worker task owner                                 | focused worker pytest, registration check                               |
| Migration/model    | Alembic/model owner                               | `pnpm check:alembic-graph`, migration test                              |
| File/network       | parser/service/security tests                     | malformed/oversized/redirect/failure-cleanup tests                      |
| AI capability      | AI owner/registry; ADR 0012 admission             | registry/direct-call/invoke/ACL tests                                   |
| Search/RAG         | Retrieval/RAG/Source Access; ADR 0009 projections | ACL/projection/source/quality tests                                     |

Focused commands:

Vitest transpiles tests without checking their TypeScript contracts. When fixtures or test helpers change, run the spec type check as well as the application type check; do not preserve removed API fields through type assertions.

```bash
pnpm exec vitest run --root apps/web <path>
(cd apps/api && uv run --python 3.12 --group dev python -m pytest <path> -q)
(cd apps/worker && uv run --python 3.12 --group dev python -m pytest <path> -q)
```

Use `pnpm ci:app-api-contracts`, `pnpm ci:app-web-contracts`, or `pnpm ci:all` only when the changed surface justifies broad validation.

## Instructions and capabilities

Scoped `AGENTS.md` files contain local contracts. `CLAUDE.md` imports the adjacent canonical file; `.claude/skills` links to `.agents/skills`; the Copilot bridge points to root instructions. New app scopes may add local contracts without editing a fixed scope allowlist.

Project skills expose specialized MIY entrypoints. The current capabilities are app integration, product AI registration, development stack operations, env contracts, native Docs extraction, release promotion, and production operations. Ordinary coding, diagnosis, design, issue drafting, browser interaction, Git isolation, and MR review use the model's normal tools and relevant owner documents. Browser CLI commands remain in [INSTALL.md](../../INSTALL.md#41-agent-browser로-셋업-화면-확인); review automation remains in [Local Codex MR Review](local-codex-review.md).

The catalog checker validates discovered skill metadata, size budgets, local links, referenced scripts, and tool bridges. It does not require a fixed skill count, fixed catalog names, or exact description phrases. Budgets constrain maintenance overhead; they do not establish model quality. Start a new native session after catalog or policy changes; persisted Workbench templates and task snapshots have separate compatibility checks.

## Local Codex hooks

`.codex/hooks.json` registers only `PreToolUse` for the native `apply_patch` payload. `scripts/codex-hooks.mjs` rejects patches to Git metadata and generated contracts, resolving paths relative to the session cwd and existing symlink ancestors. Its timeout is five seconds. Unknown or malformed patch input fails closed without echoing tool input.

There are no project startup snapshots, post-tool checks, stop gates, retry loops, or validation caches. Run affected checks explicitly and report their result. Product contracts and CI checks remain authoritative; removing automatic feedback does not waive them.

`.codex/rules/project.rules` owns native command policy, including direct upstream pushes, GitHub issue mutations, and direct production Compose mutations. An allow rule does not grant task authorization. Rules load at startup; validate candidates with `codex execpolicy check` and restart to load changed rules.

Hooks are limited deterministic checks, not a complete security boundary. Patch protection cannot cover arbitrary shell writes, hosted tools, wrappers, or every external mutation. Do not add a second shell parser or lifecycle engine. Native sandbox/authorization and server enforcement remain necessary.

Native `/hooks` review/trust is required for the exact definitions. Inspect and approve intended commands through the native interface; never fabricate trust records. Handler tests and catalog recognition do not prove lifecycle activation. Confirm a harmless allowed/denied patch in a trusted session when installing. Review runners exclude source `.codex` and `.agents` trees, so source hooks are reviewed as data and never activated.

## Evaluation and maintenance

```bash
pnpm check:skills
pnpm test:skill-harness
pnpm test:skill-scripts
pnpm test:claude-skills
pnpm test:codex-hooks
pnpm ci:harness
git diff --check
```

`ci:harness` also protects GitLab review, release evidence, deployment guards, and generated-contract publication. Those checks remain required for their affected surfaces.

The guidance evaluator runs six isolated service-free cases: localization, diagnosis followed by authorized repair, issue drafting, product AI registration, env preservation, and read-only MR review. Schema v3 judges artifact/behavior outcomes, requested mode/verification, and authority boundaries. Observed skill reads are diagnostic data only; neither reading nor skipping a skill determines success. Failed outcomes stay in the aggregate report.

Use the same explicit model, reasoning effort, installed CLI, evaluator revision, and host settings for baseline and candidate. Run at least three repetitions for an initial comparison:

```bash
pnpm eval:agent-guidance -- --variant baseline --baseline <full-baseline-sha> --model <model-id> --effort xhigh --repeat 3
pnpm eval:agent-guidance -- --variant candidate --baseline <full-baseline-sha> --model <same-model-id> --effort xhigh --repeat 3
```

Each fixture has no Git remote, uses synthetic data, disables inherited config/hooks and unavailable external services, and preserves tests/guidance. Multi-turn cases retain the native session. Live runs use Codex subscription authentication and are opt-in, outside CI; no product provider or API fallback is added. The evaluator saves aggregate metrics under ignored `.runtime/agent-guidance-eval` and removes its synthetic workspace; Codex session storage follows the native CLI's behavior.

Report outcomes, compliance, boundaries, observed reads, input/cached/output tokens, and wall time separately. Structural draft grading and command observations are limited proxies. Fewer skills or shorter instructions do not prove higher quality or lower latency. Keep historical schema results separate from v3; implementation and evaluation evidence for this transition belong in the redesign record.

## References

- OpenAI: [AGENTS.md discovery](https://developers.openai.com/codex/guides/agents-md), [skills](https://developers.openai.com/codex/skills), [native hooks](https://learn.chatgpt.com/docs/hooks), [rules](https://developers.openai.com/codex/rules).
- Anthropic: [memory](https://code.claude.com/docs/en/memory), [skills](https://code.claude.com/docs/en/skills), [best practices](https://code.claude.com/docs/en/best-practices).
- [Agent Skills specification](https://agentskills.io/specification).

Research evidence and its applicability limits are maintained in the [redesign review](../../platform-redesign/REVIEW.md), rather than duplicated here as universal prompting rules.
