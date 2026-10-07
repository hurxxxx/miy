# MIY independent app SDK

`connectApp` implements browser protocol version 1 for a separate-origin iframe or an explicit standalone login popup. It passes a short-lived, single-use PKCE exchange code; the portal's login bearer never crosses into the app. App session tokens stay in memory and must not enter URLs or browser storage.

The app reads `app_id`, `installation_id`, and `platform_origin` from its own server's `/api/config`. For a standalone connection, an explicit button opens `/apps/<appId>/installed/<installationId>?connect=popup` on that configured platform origin and passes the returned window as `hostWindow`. The portal requires its existing login.

```js
const session = await connectApp({
  platformOrigin: config.platform_origin,
  installationId: config.installation_id,
  hostWindow, // iframe: parent; standalone: the explicitly opened portal popup
});
```

The child sends `miy.app.ready` with `version: 1`, installation ID, a random request ID, and an S256 code challenge. The host validates origin, window source, installation and admission, calls the platform launch endpoint, then echoes `miy.app.launch` with the same request ID and the code to the exact app origin. Ready messages retry every 500 ms for at most 15 seconds to handle iframe load races; they reuse the same nonce. Each new connection creates a new nonce, including renewal in the same document after token expiry or a failed exchange. The host serializes launches, remembers at most six nonces for one minute, and permits at most six launches per minute per listener. A launch request times out after ten seconds; late responses and responses after navigation or a portal login change are discarded. This browser bound is not a replacement for server admission.

The SDK sends the code and in-memory verifier to the app's same-origin `/api/session/exchange`. The app server forwards them to the configured platform with its own registered origin. This avoids third-party cookies and does not open global CORS. The platform token returned by this exchange is valid only for the app installation and audience. Protected app API handlers introspect it on every request, then apply their own resource ACL.

Expiry or failed validation requires a fresh handshake. File selection, navigation APIs, product AI and product data access are not implicitly authorized. The API contract is owned by [the independent app domain](../../apps/api/src/miy_api/domains/independent_apps/README.md).

## Optional display preferences

Pass `onUIContext` and an `AbortSignal` to opt into read-only theme and language updates. The returned app session has exactly the existing shape. Keep the controller for the connection's lifetime; abort it before reconnecting and on component/document disposal. A callback without a signal is rejected before the handshake.

```js
const controller = new AbortController();
const session = await connectApp({
  platformOrigin: config.platform_origin,
  installationId: config.installation_id,
  hostWindow,
  signal: controller.signal,
  onUIContext: ({ theme, locale }) => {
    // The app owns its CSS, locale fallback and translated copy.
    document.documentElement.style.colorScheme = theme;
    document.documentElement.lang = locale;
    renderAppPreferences({ theme, locale });
  },
});
// Later, before reconnecting or disposing the app:
controller.abort();
```

The ready message adds `ui_context_version: 1`. An opted-in host adds `ui_context: {version: 1, sequence: 0, theme, locale}` to the launch message, then sends `{type: 'miy.app.context', version: 1, installation_id, request_id, ui_context}` with an increasing safe-integer sequence. `theme` is the resolved `light` or `dark` value, including system preference resolution in the portal; `locale` is a language tag bounded to 35 characters. The current portal provides `ko-KR` or `en-US`. The SDK projects only `{theme, locale}` to the callback, without tokens, user information or permissions.

Every message pins the exact origin, host window, installation, protocol/context versions and original handshake nonce. An update cannot create a channel before valid initial context is received. During session exchange, only the newest valid context is buffered; no callback runs before installation/audience/token/expiry validation succeeds. Stale sequences and malformed updates are ignored. Callback exceptions do not change the authenticated session. Theme or language changes never renew the session or request another launch code.

Old identity-only callers advertise no context capability and keep their previous behavior. A new caller with an old host, unsupported context version or invalid optional initial context still receives its normal app session; its callback is not invoked. The app uses its own default presentation in that case. This additive context extension keeps browser protocol and manifest `sdk_version: 1`. The package remains the unpublished `0.1.0` development source; there is no registry release or claim that existing vendored apps automatically receive it. New starters vendor the canonical SDK through the generated bundle. Existing apps must explicitly update their vendored SDK to opt in.

Iframe updates reflect the current host document. The portal reads its existing effective HTML theme and shared locale; this bridge does not introduce another preference store or write user settings. A standalone app receives updates only while its selected login popup remains open. After popup closure, abort, page navigation or session expiry, listeners/timers are removed and the app retains the last presentation values; reconnecting explicitly obtains the current values. Closed popups are detected by a one-second check, subject to browser background timer throttling. Changes in a different portal tab are not promised until the selected host's own preferences refresh. No background API polling, cross-tab login synchronization or browser storage of credentials is added.

The basic/private-notes starters demonstrate app-owned CSS variables, `color-scheme`, `document.lang`, Korean/English copy and a Korean fallback for other languages. They abort an earlier connection before reconnecting and on unmount. They do not import portal CSS, React components or translation resources through this SDK.

Run `node --test packages/app-sdk/src/index.test.mjs` from the checkout. The scaffold currently vendors this SDK version into the new app; no registry publication has occurred.

The 2026-10-06 UI-context slice passed 14 SDK tests, 20 portal host/component tests, 2 starter presentation/manifest tests, 42 Workbench bundle/source-preparation tests and 11 API scaffold/data-template tests. App/spec TypeScript, changed-file ESLint, formatting and the full web architecture checks passed. A production web build and 5 cross-origin Chromium cases passed with unchanged SDK/host inputs: three existing identity cases plus iframe theme/locale changes without replacing the document or renewing authentication, and popup update/close/reconnect. The iframe bootstrap can abandon an issued code when its load event replaces the host listener, then reuse its ready nonce; the context checks compare launch/exchange counts after connection, not a claim of exactly one initial launch. Browser evidence is kept at `.runtime/independent-ui-context-validation` in the development checkout and uses synthetic local origins, not production deployment-domain proof.

Final canonical starter inputs also passed actual Docker UI build/activation/rollback in 8.25 seconds and the PostgreSQL notes-container/session/proxy/rollback test in 20.50 seconds; owned resources were cleaned. The generated Workbench bundle was regenerated through `scripts/generate-app-starters.py` and its consistency check passed. These are local validation results, without registry publication, service installation or production deployment.

## Optional app navigation offers

Pass `onNavigationReady` and an `AbortSignal` to receive a connection-scoped `offerApp` function after the normal app session is validated. The function accepts only `{appId, installationId?}`. A registered independent app requires its exact installation ID; a built-in app uses its canonical app ID. Paths, URLs, query parameters, window targets and resource IDs are not accepted. This extension does not change the session return object, manifest SDK version or any API permissions.

```js
let offerApp;
const controller = new AbortController();
const session = await connectApp({
  platformOrigin: config.platform_origin,
  installationId: config.installation_id,
  hostWindow,
  signal: controller.signal,
  onNavigationReady: (offer) => { offerApp = offer; },
});
// In an app-owned action, when the callback was provided:
const result = await offerApp({ appId: 'planner' });
// result.status: 'offered', 'busy', or 'unavailable'
```

`offered` means that the portal displayed a suggestion. It does not mean the user accepted it or reached the destination. Only a separate button click inside the portal can move the portal window. In standalone mode this moves the selected login popup; it never moves the original app window, another tab or a top-level opener. If the host does not advertise navigation support, the callback is never invoked and the normal session still succeeds. Keep an app-owned fallback for that case. Invalid input, an expired/closed connection or a ten-second request timeout rejects with a fixed local error; it never returns raw server errors.

The optional capability is `navigation_version: 1` on ready and launch. Requests use `{type: 'miy.app.navigation.request', version: 1, navigation_version: 1, installation_id, request_id, navigation_id, target: {app_id, installation_id?}}`. The result echoes those identifiers with `type: 'miy.app.navigation.result'` and a status. No token, identity, permissions or arbitrary payload enters these navigation messages. Messages require the original handshake nonce and exact window/origin/installation. The SDK allows one pending request and at most six per minute; the host independently bounds requests and retains one visible offer for at most thirty seconds. Flooded/replayed messages are ignored. The optional host channel ends on a new nonce, host disposal, popup closure or its five-minute maximum lifetime; the SDK also ends at its actual app-session expiry. Timers can be throttled in background tabs, so click-time checks also compare current time and window state synchronously.

Before displaying an offer and again after a host click, the portal fetches current bootstrap admission and the complete revision-consistent independent catalog. It verifies the current logged-in actor, source installation/origin/generation/installed entrypoint, and the exact admitted target. Built-in destinations use owned canonical route contracts; independent destinations use only their encoded app/installation route. A changed target release, origin, generation or entrypoint invalidates the earlier offer. Each lookup is bounded; late results after a login, source document, installation or popup change are discarded. No request automatically navigates or performs an installation/session mutation. These are admission snapshots for presentation, not a transaction spanning the network and browser navigation: destination routes and resource APIs continue to enforce current server admission and ACLs. The host issuing a launch code is not proof that the app completed its session exchange.

Offers are ephemeral. Dismissal, expiry, failed click-time admission and connection changes remove the button; no browser-storage queue, navigation receipt or automatic retry is added. The app owns whether to offer the action again. Existing vendored apps receive this capability only after an explicit SDK update; starter bundle regeneration remains part of the canonical source packaging check.

## Optional selected-file reads

File name and content-type metadata limits count up to 255 Unicode code points, matching Core; non-BMP characters such as emoji count once.

`onFilePickerReady({ selectFile })` opts into `file_picker_version: 1` and requires the connection's `AbortSignal`. The callback is exposed only after the normal app session validates, the host negotiates support, and the session includes both `identity:read` and `files:read-selected`. The returned session object is unchanged. An old host, unsupported capability or missing permissions still permits the normal connection, without this callback. Existing installations receive no new permission automatically.

```js
let selectFile;
const controller = new AbortController();
const session = await connectApp({
  platformOrigin: config.platform_origin,
  installationId: config.installation_id,
  hostWindow,
  signal: controller.signal,
  onFilePickerReady: (files) => { selectFile = files.selectFile; },
});
// Explicit app-owned action; the portal owns the picker and confirmation.
const result = await selectFile();
if (result.status === 'selected') {
  const { fileId, name, contentType, sizeBytes, version } = result.file;
  const readController = new AbortController();
  const bytes = await result.read({ signal: readController.signal });
  // ArrayBuffer, at most 10 MiB. The app owns subsequent use of these bytes.
}
```

`selectFile()` accepts no resource ID, path, URL, query or authority. It returns `{status: 'canceled' | 'unavailable' | 'busy'}` or `{status: 'selected', file: {fileId, name, contentType, sizeBytes, version}, readGrant, expiresAt, read}`. Metadata is informational; `contentType` is not permission to render active content. `readGrant` is an opaque credential for an app-owned backend when accompanied by this same app bearer. Keep it only in memory or an explicitly authorized server request: never put it in a URL, browser storage, logs or an LLM prompt. No platform login bearer, Files listing, object-store key or download URL crosses this protocol. Bytes already delivered cannot be recalled by later revocation.

For every selection, the SDK sends a fresh UUID and `{schema_version: 1, selection_id}` to its same-origin `/api/platform-files/selection-request` with its app bearer. The app backend fills its fixed installation/audience. The bounded 60-second proof then travels to the exact host window with the original handshake nonce. Host UI validates current source identity and obtains its own server-checked candidates; only a separate host confirmation can authorize the chosen file/version. The correlated result carries exact context, one bounded metadata object and a short read grant (Core maximum 120 seconds, also capped by actual session expiry). `selected` is authorization for that file, not evidence that bytes were read.

Ready/launch advertise `file_picker_version: 1`. Requests use `{type: 'miy.app.file-picker.request', version: 1, file_picker_version: 1, installation_id, request_id, selection: <Core proof DTO>}`. Results use the same pinning fields with `type: 'miy.app.file-picker.result', selection_id, result: {status: 'selected', selection: <Core selected DTO>}` or a fixed status-only result. Cancellation uses `miy.app.file-picker.cancel` and the exact selection ID. SDK and host each allow one pending picker and at most six requests per minute. Proof fetch has a five-second deadline; picker lifetime is bounded by proof/session/channel expiry and sixty seconds. Abort, document exit, popup closure or disposal invalidates pending work and SDK callbacks. A new host nonce closes the previous host picker/request; before reconnecting, the app must also abort its previous controller to invalidate already returned SDK read closures. An already delivered opaque grant is not revoked merely by closing a picker or issuing another nonce: its server-enforced expiry and current authority checks still apply. A timed-out selection does not automatically open another picker. Background timers may be delayed; current-time/window checks also run synchronously before accepting results.

`read({signal?})` fetches only same-origin `/api/platform-files/content`, using the original app bearer and `X-MIY-Selected-File` header. The SDK accepts only a complete `application/octet-stream` response matching selected size, with a fixed 10 MiB cap, a twenty-second deadline covering response-body completion, no redirects, no cookies and no automatic retries. It permits one concurrent read per connection and releases a canceled or invalid body. A read after grant expiry, connection disposal or popup closure rejects with a fixed local error. Each actual server read independently rechecks current app/source sessions, installation permission/generation, Files admission/ACL and the selected object/version; the SDK's checks do not replace those server checks. This feature does not expose upload, deletion, ranges, archive extraction, arbitrary URLs or general platform APIs.
