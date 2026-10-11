# Project Skill Contracts

- Keep project skills in `.agents/skills`; tool bridges share this catalog.
- Each skill exposes a MIY-specific capability, its input/output, and important boundaries. General development procedures belong to the model, not a mandatory skill.
- Descriptions support discovery; no fixed trigger wording or skill count is required. Load only relevant resources.
- Keep common authority in root `AGENTS.md` and link to contract owners instead of duplicating policy.
- Preserve deterministic helpers and test their behavior. Check metadata, local references, and bridges when changing the catalog.
- Evaluate task outcomes and authorization boundaries; skill reads are observations, not success criteria.
