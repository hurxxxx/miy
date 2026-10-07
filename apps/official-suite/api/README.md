# Official API composition artifact

`miy_official_api.main:app` is the ASGI entrypoint for the official API wheel. It reuses the existing MIY application factory, router handlers, authentication dependencies, resource ACL and AI contracts. It does not create another identity protocol or copy business handlers. The selected routes are owned by `miy_api.official_api_registry`; the platform-only entry is `miy_api.platform_main:app`. `miy_api.main:app` remains the active legacy composition and preserves all routers in their existing order.

This artifact is **inactive**. HTTP business traffic returns 503 and WebSocket business traffic closes with 1013 before any handler runs. `/healthz` reports only that the artifact can respond, with `activation: inactive`; `/readyz` always returns 503 `service_not_activated`. OpenAPI/docs remain inspectable. No environment flag or request header bypasses this boundary. Constructing either split composition with runtime initialization enabled is rejected. Inactive composition does not initialize PostgreSQL, object storage, AI registries, Hermes sockets or collaboration services, nor mount the legacy frontend/desktop update feed.

From the repository root:

```bash
pnpm nx api-contract official-suite
pnpm nx api-build official-suite
```

The build produces the official entry wheel and its matching MIY API compatibility wheel in `dist/apps/official-suite-api`. Both come from the same checkout; the shared dependency still contains existing platform/business source and the common runtime dependencies remain owned by `apps/api/uv.lock`. The separate [inactive image recipe and offline artifact check](../../../ops/official-suite-api/README.md) package both wheels, existing runtime configuration and the real collaboration codec from stable inputs. It is not added to the production compose/release contract. Source extraction, service authority and writer activation remain separate work.

The [core identity bridge](../../api/src/miy_api/domains/official_apps/README.md) now connects explicitly approved app sessions to the original `AuthContext` for owned official HTTP app scopes. It binds the current verified artifact and installation generation, rechecks admission, preserves source ACLs and avoids login-session last-seen writes. Approval is an internal core operation with no app-facing endpoint. The bridge still reads shared core authority tables; remote introspection, service DB roles and WebSocket delegation remain pending. The inactive gate above remains in force.

| Artifact                  | Current state                                                                                        |
| ------------------------- | ---------------------------------------------------------------------------------------------------- |
| Official UI               | Separate entry/build output; legacy UI/public-module bridge                                          |
| Official API              | Separate wheel/ASGI entry and owned route/schema set; activation closed                              |
| Platform API              | Separate ASGI entry within the existing API wheel; activation closed                                 |
| Legacy API                | Existing active composition, runtime initialization and single writer                                |
| Worker / Beat             | Active legacy worker; separate inactive platform/official profiles and owned queues, no new consumer |
| Service image             | Local inactive image recipe and offline check; no production release contract                        |
| Routing / database writer | No activation or production cutover                                                                  |

The [worker owner](../../worker/README.md) records the inactive profiles, matching wheel evidence and remaining claim/lease/outbox activation requirements.

The [cutover owner](../../../platform-redesign/OFFICIAL_API_CUTOVER.md) records the concrete shared writes, fencing, identity delegation, router generation, database roles and worker/outbox steps required before activation. Publishing a health endpoint or building a wheel does not satisfy those steps.
