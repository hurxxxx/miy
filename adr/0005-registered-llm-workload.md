# ADR 0005: Registered LLM Workload and Common Execution Interface

- Status: Accepted; scope policy superseded by [ADR 0012](0012-company-app-access-without-workspaces.md)
- Date: 2026-07-10

Current admission follows [App Platform](../docs/domains/app-platform/README.md),
and durable execution follows [AI Execution](../docs/domains/ai/execution.md).
This ADR retains workload registration and provider-routing decisions.

## Decision

- Every generative or decision model call registers `RegisteredLlmWorkload` in `AiCapabilityRegistry`.
- Domain hook: `register_ai_capabilities(registry)`.
- `workload_id` is a stable namespaced server constant.
- Workload unit = independently configurable execution function/stage.
- Legacy `task_kind` may remain for budget/audit compatibility; `workload_id` is discovery key.
- Domain service/worker calls only `execute_llm(...)`, `stream_llm(...)`, or `execute_decision(...)`.
- Caller passes workload, app, actor, personal/company execution context, and input.
  Caller never chooses provider/raw model key/pool/endpoint/credential. Explicitly opted-in workloads may accept a catalog model ID through the common resolver; current route/capability/security policies still apply.
- Common execution resolves route/provider/model/output cap once from descriptor plus admin override.
- External security allow/mask/block/audit never reroutes. Block fails closed.
- Provider implementations are approved adapters behind the common interface.
- Generation defaults to Hermes. Latency-sensitive single-response workloads may explicitly register `direct_completion` through the same gateway; this is never an app-local bypass or a Hermes failure fallback. Registration, compatible transport, schema validation and retry limits are owned by the [gateway contract](../docs/domains/ai/gateway.md#direct-completion-exceptions).
- `execution_kind="agent"` uses `AgentRuntimeAdapter`, separate from one-shot `LlmExecutionAdapter`.
- `execution_kind="decision"` uses a native decision adapter and the same routing, admission, egress and audit boundary; it does not emulate chat or invoke an agent loop. Company/app defaults are partitioned by generation/decision family. Native decision limits and typed choice/score/probability semantics are owned by [AI Gateway](../docs/domains/ai/gateway.md#decision-workloads).
- Embedding/rerank/OCR/ASR are outside this ADR and use Inference Gateway.

## Admin Surfaces

- Admin projects registry snapshot plus DB overrides; no hardcoded workload list.
- New workload appears with default route without DB seed.
- DB stores provider/model settings and workload overrides only.
- Workload route override is the only local/external selection source.
- Output cap defaults: local 32K, external 64K.
- Approved model catalog controls route choices; discovery never auto-approves models.
- API responses/UI never return API key plaintext.
- Management groups: LLM Providers, Model Catalog, LLM Routing, AI Security, Audit Logs.
- Document-processing vision workloads keep registry/audit but use `management_surface="document_processing"`.
- Web search/page extraction is provided by interactive Hermes chatbot tools; the standalone Web Search app is retired. Workloads retain explicit route admission and no automatic fallback.

## Required Change Unit

- stable `workload_id`
- local/external output caps for generation; bounded input/question/response contract for decisions
- common execution call
- audit/tracing and external-data policy
- registry/bootstrap/duplicate/adapter/default-route tests
- provider/core direct-call guard test

## Do Not

- Add app-local workload registry, file scan, direct SDK/HTTP call, or route fallback.
- Let AI Security choose a different route.
- Store task-kind local/external policy outside workload routing.
