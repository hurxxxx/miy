---
name: miy-release
description: MIY dev-to-main release promotion evidence and protected branch contract. Excludes production checkout updates and deployment.
---

# Release Promotion

The [release owner](../../../docs/domains/release/README.md) defines required evidence and rollout compatibility. Root authorization applies separately to MR creation, merge, source update, and deployment.

Protect remote `dev` and `main`; never remove `dev` as a release MR source. Evidence must match the latest source SHA or equivalent merge result. Verify mergeability, required checks, env/migration compatibility, image evidence, and rollback compatibility.

Full validation is the default. An explicit simplified/urgent/fast request may select the owner's [impact-based validation](../../../docs/domains/release/README.md#impact-based-release-validation); unsupported scope falls back to full checks. Failed checks and production rollout gates remain binding.
