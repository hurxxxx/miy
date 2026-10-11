---
name: miy-ai-capabilities
description: MIY product AI capability registration, workload routing, discovery, approval, and audit. Excludes native coding-client orchestration and ordinary UI changes.
---

# Product AI Integration

Owners: [AI Gateway](../../../docs/domains/ai/gateway.md), [capability architecture](../../../adr/0002-mcp-capability-platform.md), and [current app admission](../../../adr/0012-company-app-access-without-workspaces.md).

Register tools through `register_ai_capabilities(registry)` / `AiCapabilityRegistry` using AI-specific DTOs. Write tools require discovery predicates, execution ACL, approval, and audit. Register each independently configurable function/stage as a `RegisteredLlmWorkload` and use `execute_decision`, `execute_llm`, or `stream_llm` as appropriate.

The gateway owns providers, credentials, routes, output limits, and validated model-catalog opt-in. Decision outputs cannot authorize access. Direct completion exceptions follow the gateway contract; no app-local provider calls or fallback.

Focused checks run from `apps/api`:

```bash
uv run --python 3.12 --group dev python -m pytest tests/test_platform_adapter_registries.py tests/test_ai_gateway_direct_call_guard.py tests/test_ai_capability_compile.py -q
```
