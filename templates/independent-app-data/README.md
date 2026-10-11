# Private notes starter

This starter extends the basic independent app with owner-only notes. Its local [platform capabilities](PLATFORM_CAPABILITIES.md) describe the session, fixed record gateway, permissions and storage bounds without a MIY source mount. Generate it from the MIY source checkout:

```bash
uv run --frozen --directory apps/api python ../../scripts/independent-app-env.py scaffold /absolute/new-notes --template private-notes --app-id my-notes --name 'My notes' --repository https://git.example/team/my-notes.git
```

The generated repository is self-contained. `business.py` owns note validation and routes; the core gateway only understands bounded owner-scoped JSON records and collections. No database credentials, SQL or caller-selected user ID enter the app. The app session stays in browser memory and every CRUD request is checked against current platform admission and grants. Updating/deleting records uses an expected version so another window's work is not silently overwritten.

The notes UI shares the basic starter's app-owned Korean/English copy and CSS theme example. Its SDK display-preference callback updates presentation after session validation and keeps business requests on the same app session. Reconnection aborts the previous subscription; closing the login popup retains the last display values without promising cross-tab preference synchronization.

Register the manifest and explicitly grant `identity:read`, `data:read`, and `data:write` to the installation. A core operator must configure the separate data cluster and execute the verified local delivery flow before using the notes API. The `web-api-postgres-v1` profile invokes the core v1 migration before activation. Data configuration, migration journal, failure recovery and credential-key rotation remain operator-owned; their app-visible boundary is in the local [platform capabilities](PLATFORM_CAPABILITIES.md). This app uses the public `MIY_APP_ID`, `MIY_APP_INSTALLATION_ID`, `MIY_APP_ORIGIN`, and `MIY_APP_PLATFORM_ORIGIN` settings, with distinct app/platform origins. For an explicitly owner-operated trusted checkout, install its dependencies with `pnpm install` and `uv sync`, then run `uv run uvicorn api:app --host 127.0.0.1 --port 8000` and `pnpm dev` separately. The app's `pnpm build` produces `dist/`. These commands do not configure the Core data service or authorize host operations by an app manifest.

Different installations, including development and production, have different databases and roles. Development rows are never copied during code promotion. Code rollback preserves rows and the forward-only v1 schema. Production uses the platform's explicitly configured Core-admin same-host promotion of an observed development artifact; Workbench development grants cannot approve it. Custom SQL migrations, remote registry delivery, worker jobs and object storage require separate implemented contracts.
