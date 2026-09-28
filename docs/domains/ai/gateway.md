# AI Gateway

Generative and decision model calls use registered workloads and the common execution gateway. App code never chooses provider SDK or external HTTP endpoint.

Approval replay, graph execution, and artifact state are owned by [AI Execution](execution.md).

## Contract

- Workload registers ID, owner, routes, capability, output cap, audit/tracing, external-data policy.
- Admin saves multiple named connections (OpenRouter, OpenAI, Anthropic, Gemini or OpenAI-compatible). Connection IDs are distinct from provider/transport kinds. Local connections support optional API-key authentication.
- Generation and decision each have independent global defaults → app defaults → `(app_id, workload_id)` overrides select connection/model/output cap per local/external route. Omitted values inherit; saving only a cap does not pin a resolved model. Output caps resolve explicit workload → app → global values, then the registered workload default (32K local / 64K external unless the workload declares another default). Untouched migration-seeded global caps are cleared by `llm_cap_defaults_20260918`; administrator edits are preserved. Generation global model changes use the selected connection default, while app/workload model overrides stay explicit. Decision defaults always store an explicit decision model and never inherit the generation connection default. Existing rows migrate to `generation`; no decision default is seeded.
- Runtime policy is DB-only: missing/disabled connections, missing credentials, inactive catalog models, incompatible capabilities and disallowed routes fail closed. No unique-provider or environment fallback is used. Provider allowlists remain infrastructure/security policy.
- External connections must also be admitted by both `OPEN_WORK_HUB_LLM_EXTERNAL_ALLOWED_PROVIDERS` and `OPEN_WORK_HUB_AI_ALLOWED_EXTERNAL_PROVIDERS` using their provider kind (for example `openrouter` or `openai_compatible`). Saving a connection does not widen either deployment allowlist; local compatible connections use the local host policy instead.
- App catalog registrations declare `ai_capability_modules`; the AI registry imports each hook once and fails for missing hooks. A shared workload has independent settings for each owning app.
- Retired app/workload overrides remain visible as orphaned settings. Administrators may reset them using their stored app/workload identity, current registry digest and row version; model references remain protected until reset.
- Credentials are encrypted per connection with `OPEN_WORK_HUB_AI_MODEL_CREDENTIAL_ENCRYPTION_KEY`. GET returns only `has_api_key`; omission preserves, replacement rotates, explicit clearing removes the key. The master key remains outside the DB and must be preserved for restores.
- Hermes structured output and tools require `tool_calling`, including tools/schema supplied at runtime. Direct completion uses the provider's JSON Schema response format instead of tools (see below). Model discovery does not approve capabilities automatically. Override writes validate the effective inherited route using the execution resolver before commit. Saved connection probes release the DB during I/O, recheck both connection and selected-model versions, and are invalidated by model edits/discovery.
- `execute_llm` and `stream_llm` return safe execution metadata, never credential-bearing transport configuration. Interactive Hermes sessions retain their lifecycle while resolving the same model policy.
- No local/external automatic fallback.
- External transfer passes classification, masking, approval policy, and audit.
- Graph planning egress uses the provider kind from the registered workload's resolved external execution. A local route or unresolved provider cannot activate external planning; search retains its separate configured provider.
- Tool execution checks the current user/execution principal, owning-app admission, descriptor discoverability, and
  source ACL; write tools also require approval.
- Audit records actor, app, workload, provider/model, token usage, trace ID and generation runtime adapter.
- Registered generation defaults to [Hermes](hermes.md), including streaming, tools and agent loops. Only explicitly registered [direct completion exceptions](#direct-completion-exceptions) bypass the Hermes runtime. Administrator workload policy still resolves model, data transfer and caps before dispatch. Hermes failures never activate direct completion as a fallback.
- `AgentRuntimeAdapter` preserves the application orchestration interface; Bento registers only the Hermes implementation.
- `execution_user_id` declares a private runtime owner for system work without replacing its audit actor.
- `LlmCompletionResult.structured_output` is validated by the selected common runtime. Apps apply their semantic checks without parsing provider envelopes.

## Direct completion exceptions

Use `direct_completion` only for latency-sensitive, single-response generation that needs no agent loop, tools, conversation workspace or streaming. Hermes remains the default. Native semantic decisions continue to use `execute_decision`, not a chat emulation.

An owner explicitly registers the exception; callers cannot enable it with a per-request flag:

```python
registry.register_llm_workload(
    workload_id="example.bounded_choice", task_kind="example_bounded_choice",
    owner_domain="example", app_id="example", description="One structured choice",
    required_capabilities=("chat",),
    default_runtime_adapter="direct_completion",
    allowed_runtime_adapters=("direct_completion",),
    local_max_output_tokens=1024, external_max_output_tokens=1024,
)
```

Call the same `execute_llm(..., output_schema=...)` interface. The gateway resolves the registered/DB runtime, owner admission, catalog model, encrypted credentials, output cap and external security/masking before dispatch. The common core adapter uses the existing OpenAI-compatible transport and official SDK. OpenRouter, OpenAI and registered compatible connections are supported; incompatible provider transports fail during route resolution. Direct endpoints are revalidated against the common local-host/public-HTTPS policy, redirects are disabled and clients close after each attempt. No new environment variable or credential source is introduced.

Structured requests use `response_format: {type: "json_schema", json_schema: {strict: true, ...}}`. Models/endpoints must support this format; `chat` capability alone is not proof. OpenRouter uses `require_parameters=true` and `allow_fallbacks=false` per its [structured-output](https://openrouter.ai/docs/guides/features/structured-outputs) and [provider-routing](https://openrouter.ai/docs/guides/routing/provider-selection) contracts. No response-healing plugin is enabled. Other compatible servers may reject unsupported schemas; there is no downgrade to free text or tool calling.

The adapter validates JSON and the supplied schema server-side, forbids remote schema references, and rejects truncated/refused/empty responses, duplicate keys, non-JSON numbers and schema violations. Text-only completion is also supported when no schema is supplied. Native tools, tool parameters, streaming and transport overrides are rejected. Do not use this exception for AI write execution or agent workflows.

Each attempt makes one provider request with a timeout, SDK retries disabled and no model/runtime fallback. The existing audit records success/failure, runtime, model, latency and usage once; errors do not retain provider response bodies. The caller owns bounded or cancellable retries. `tetris.play.generation` opts in and retains its game-scoped 500ms retry contract. Its latency still includes model inference and network time; bypassing Hermes does not guarantee a fast model.

The direct adapter explicitly sends the resolved reasoning effort as OpenRouter's `reasoning.effort`; the shared Hermes payload profile does not encode that field. Provider defaults must not silently replace the admitted effort. Rate limiting, output-budget exhaustion and timeouts expose safe `LlmRuntimeError.reason_code` values (`rate_limited`, `output_limit`, `timeout`) through the high-level helper. Apps may localize these categories; never display raw provider exception bodies.

## User model selection

`RegisteredLlmWorkload.allow_model_selection` defaults to false. An opted-in workload may pass an opaque catalog entry ID as `selected_model_id` through `execute_llm` or `execute_decision`. This selects a model for one call; it does not write administrator defaults. Raw provider/model keys, credentials, endpoints and routes remain server-owned.

The common resolver first determines the workload's configured local/external route, runtime and output caps. It then resolves the selected entry's connection and rechecks enabled/active status, capabilities, credentials, route compatibility and both external-provider allowlists. Selection cannot switch the configured route or bypass egress/security/owner admission. An absent selection preserves the existing inherited defaults. A rejected selection never falls back to another model.

`list_selectable_workload_models` uses the same resolver and returns only catalog IDs, display names, model keys, provider kinds and the default marker. App endpoints still enforce current app admission. Each execution revalidates the selection even if the list was loaded earlier. Only the two Tetris play workloads currently opt in. Model lists perform no inference.

## Non-reasoning workloads

Latency-sensitive chat workloads declare `required_capabilities=("chat", "non_reasoning")`.
The common gateway forces `reasoning_effort="none"` and removes caller transport options that
could enable thinking, including when a caller requests another effort. This policy applies to
inherited defaults and every user-selected model; other workloads retain their own effort.
Lower-level gateway requests that contradict the policy are rejected before provider I/O.
This contract is currently limited to chat workloads, not native decisions or agent loops.

`non_reasoning` is an administrator-approved model capability: the model/endpoint must support
answering without reasoning. Required-reasoning models and unverified catalog entries fail the
same capability checks for listing, route saves and execution. There is no automatic fallback to
`low`, another model or another runtime. OpenRouter discovery proposes this capability only when
its reasoning metadata explicitly reports `mandatory=false`; missing metadata does not prove
support. Discovery keeps new models disabled and preserves existing administrator capability
approvals. For an existing or manually registered model, verify the endpoint and approve
**Respond without reasoning** in the model catalog. Tetris generation uses this policy.

## Local Runtime

- Register the endpoint and optional key in Admin → LLM connections. vLLM and Ollama presets use OpenAI-compatible `/v1` endpoints; OWH does not install/start these servers or manage model downloads/GPU allocation. The selected model must actually support the declared tools/stream/structured behavior.
- Local endpoint hosts must be listed explicitly in `OPEN_WORK_HUB_LLM_LOCAL_ALLOWED_HOSTS`; include the address reachable from API and Hermes. Metadata, link-local and multicast addresses are rejected. External endpoints require public HTTPS on port 443. Model discovery does not follow redirects.
- Use the saved-connection test after approving a model. This checks reachability/model availability; it does not certify every capability. Verify an actual structured/tool workload before switching the global default.
- Model availability/defaults live in Admin model catalog/routing, not env or app code. Explicitly opted-in workloads can accept a validated catalog selection as described above.
- Non-secret LLM timeouts and preprocessing-model defaults live in the tracked
  [runtime configuration](../release/README.md#public-runtime-configuration); active model routing stays in the database.
- Docker Model Runner profile uses OpenAI-compatible API.
- Dev default: `http://127.0.0.1:12434/engines/v1`.
- Use `scripts/dev-local-qwen.sh` for model install/status/smoke.
- Qwen `reasoning_effort=none` maps to `chat_template_kwargs.enable_thinking=false`.
- Runtime health retains connection identity, including multiple connections of one provider family; local serving status enumerates enabled local connections.
- Legacy core adapter types remain for transport/health compatibility; application generation enters only the registered gateway.

## Decision workloads

Use deterministic code for exact validation, arithmetic and authorization. Use a decision model for bounded semantic classification, choosing among defined options, ordinal scoring or estimating a proposition's probability. Text synthesis and open-ended reasoning remain generation. Embedding, rerank, OCR and ASR keep their role-specific Inference Gateway interfaces.

Register through the existing app hook, without a second registry:

```python
registry.register_llm_workload(
    workload_id="example.triage", task_kind="example_triage",
    owner_domain="example", app_id="example", description="Classify a case",
    execution_kind="decision", required_capabilities=("decision",),
    default_runtime_adapter="decision", allowed_runtime_adapters=("decision",),
    default_route="external", allowed_routes=("external",),
)
```

The app owns its stable workload constant and source ACL. Pass source `sensitivity_labels`, `source_kinds` and `content_origin` when calling the facade; do not relabel internal/retrieved content as a public user prompt. A caller supplies identity and input, never a provider/raw model key/connection/credential. Explicit catalog selection follows the opt-in contract above:

```python
from open_work_hub_api.domains.ai.decisions import execute_decision, ChoiceQuestion
from open_work_hub_api.domains.ai.gateway import LlmWorkloadContext

result = execute_decision(
    "example.triage",
    LlmWorkloadContext(source="example.triage", actor_user_id=user.id, app_id="example"),
    db,
    state={"case": authorized_text},
    questions={"category": ChoiceQuestion(
        instructions="Choose the relevant category.",
        options={"delivery": "Shipping or delivery", "payment": "Billing or payment"},
    )},
)
answer = result.response.answers["category"]
```

`ChoiceQuestion` returns a choice, distribution and optional provider confidence. `ScoreQuestion(levels=[...])` returns a continuous score from zero to `len(levels)-1`, with an ordinal distribution and optional confidence. `ProbabilityQuestion(true_description=..., false_description=...)` returns a probability in [0, 1]. The provider wire term `noul` is private to `decision_adapters.py`. Confidence is provider-reported, not a calibrated guarantee. Apps own thresholds, abstention/human review and downstream actions; no result grants app/resource access or write approval.

`decision_contracts.py` owns bounds: state is a string, JSON object or array; at most 32 questions, 2–32 choices/levels, 64-character identifier keys, 4096-character instructions/descriptions, 256 KiB UTF-8 input and response, and a 30-second native request timeout. All answer keys/types, choices, finite values, distributions and score ranges are checked. Calls are nonstreaming, with no retry, provider fallback or chat emulation. Unknown usage/cost stays absent, never becomes zero.

Native calls use the common DB resolver, active execution-owner/app admission, existing `llm` security policies and audit path. The gateway scans a JSON security projection containing state, keys, numbers, question instructions and option descriptions; only the validated structured payload reaches the native endpoint. Masking may change string values, but invalid JSON or altered keys/container shape/scalar types fails closed. Raw state/questions/answers and credentials are not logged. `llm_call`/AI interaction compatibility is preserved with `execution_kind=decision`, workload/connection/provider, requested/actual model, tokens, optional reported cost, latency and status. Existing detector-specific security monitoring remains governed by the security owner.

The first native adapter uses OpenRouter's [public alpha Decisions endpoint](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request), which is not part of the pinned OpenAI SDK's chat surface. It uses HTTPS, no redirects, bounded response reads and safe error codes; only the canonical OpenRouter endpoint is supported. Model IDs are administrator configuration, not adapter branches. The alpha API may change: adapt the isolated wire contract and its fixture/live tests when upgrading. Future providers register a native adapter through the provider descriptor/composition root. `register_decision_adapter` is a composition/test seam, never an application routing override.

OpenRouter discovery queries both text and decisions inventories and uses `architecture.output_modalities`, not model names, to classify capabilities. New discoveries remain disabled pending approval. Saving defaults checks model capability and versions. Admin model inventory checks perform no inference or quality evaluation. Live runtime health for decision workloads uses this inventory rather than chat completion health. A page view never performs paid inference.

After setup, use a registered synthetic workload through `execute_decision` with authorized execution identity to explicitly test a real provider; verify category/score/probability semantics and exactly one audit event with actual model and usage. Do not send customer data as a smoke test. Compare reordered choices, repeated calls, Korean input and positive/negative cases before selecting application thresholds. Record latency and reported cost separately from correctness; a successful transport check is not an accuracy evaluation.

Focused regression checks:

```bash
(cd apps/api && uv run --python 3.12 --group dev pytest tests/test_decisions.py tests/test_ai_gateway.py tests/test_llm_connection_policies.py tests/test_ai_model_discovery.py tests/test_ai_gateway_direct_call_guard.py tests/test_hermes_gateway_entry.py -q)
```

Follow the [validation harness](../../agents/vibe-coding-harness.md) for shared backend/frontend/contracts, migration and instruction changes.
