# PMS App

PMS owns spaces, folders, lists, tasks, and links to Docs/Whiteboard/Planner/Meeting/AI flows.

- Runtime help source: `packages/official-suite-web/public/help/pms/user-guide.html`.
- Do not duplicate PMS user manual in `docs/apps/pms`.
- AI write approval rules: [AI Write Policy](../../domains/ai/write-policy.md).

The full browser implementation is owned by `packages/official-suite-web/src/pms`; previous web paths are compatibility exports. The narrow API/picker entry is unchanged and the full module composition is exposed separately. Korean/English app messages are composed by the existing root. The help HTML keeps `/help/pms/user-guide.html` and `#english`; the fixed two-asset Vite adapter serves it during development and emits the same bytes into both production compositions. This source move does not activate a separate PMS service or change authorization, task data, callbacks or storage.
