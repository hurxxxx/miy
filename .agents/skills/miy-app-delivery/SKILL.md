---
name: miy-app-delivery
description: MIY app registration and platform extension contracts for new or ported apps. Routine app UI and fixes need no delivery workflow.
---

# App Integration

[App Platform](../../../docs/domains/app-platform/README.md) owns current registration, admission, and extension contracts. [Platform redesign](../../../platform-redesign/README.md) records the approved transition; do not force a new independent app back into legacy shell/API composition.

Inspect the target app's definition and supported integration points. Keep discovery separate from source configuration, runtime installation, and release readiness; missing management metadata cannot hide an app. Never infer write or deployment authority from registration.

Server admission/ACL, registered AI execution, durable app state, and generated contracts remain required. Workers must be discovered by the deployed runtime; migrations must preserve supported data and rollback compatibility. Implement missing integration points at their owner and verify both accepted and denied behavior.
