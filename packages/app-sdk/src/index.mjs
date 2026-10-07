/** Independent app protocol v1. No platform login token enters this module. */
import { APP_FILE_PICKER_VERSION, createFilePicker } from './file-picker.mjs';
export { APP_FILE_PICKER_VERSION } from './file-picker.mjs';

export const APP_PROTOCOL_VERSION = 1;
export const APP_UI_CONTEXT_VERSION = 1;
export const APP_NAVIGATION_VERSION = 1;

function navigationTarget(value) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).some(
      (key) => !['appId', 'installationId'].includes(key),
    ) ||
    typeof value.appId !== 'string' ||
    !/^[a-z][a-z0-9-]{1,63}$/.test(value.appId) ||
    (value.installationId !== undefined &&
      (typeof value.installationId !== 'string' ||
        !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(
          value.installationId,
        )))
  )
    throw new Error(
      'A bounded app ID and optional installation ID are required',
    );
  return {
    app_id: value.appId,
    ...(value.installationId !== undefined
      ? { installation_id: value.installationId }
      : {}),
  };
}

function uiContext(value) {
  if (
    !value ||
    value.version !== APP_UI_CONTEXT_VERSION ||
    !Number.isSafeInteger(value.sequence) ||
    value.sequence < 0 ||
    !['light', 'dark'].includes(value.theme) ||
    typeof value.locale !== 'string' ||
    value.locale.length > 35 ||
    !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(value.locale)
  )
    return null;
  // Never forward arbitrary host fields to an app callback.
  return { sequence: value.sequence, theme: value.theme, locale: value.locale };
}

function origin(value) {
  const url = new URL(value);
  if (
    url.origin !== value ||
    url.username ||
    url.password ||
    (url.protocol !== 'https:' &&
      !(
        url.protocol === 'http:' &&
        ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      ))
  ) {
    throw new Error(
      'An exact HTTPS origin (or loopback development origin) is required',
    );
  }
  return value;
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replaceAll('=', '');
}

/**
 * Complete one launch. Call again after expiry; keep the returned app token in memory.
 * A standalone app can use a trusted portal popup as hostWindow. The popup must
 * already have a platform login; this function never transports that login.
 */
export async function connectApp({
  platformOrigin,
  installationId,
  hostWindow,
  window: appWindow = globalThis.window,
  crypto: webCrypto = globalThis.crypto,
  signal,
  onUIContext,
  onNavigationReady,
  onFilePickerReady,
  timeoutMs = 15000,
  exchange = async (payload) => {
    const response = await fetch('/api/session/exchange', {
      method: 'POST',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok)
      throw new Error(`App session exchange failed (${response.status})`);
    return response.json();
  },
}) {
  if (
    onUIContext !== undefined &&
    (typeof onUIContext !== 'function' || !signal)
  ) {
    throw new Error('UI context requires a callback and an AbortSignal');
  }
  if (
    onNavigationReady !== undefined &&
    (typeof onNavigationReady !== 'function' || !signal)
  ) {
    throw new Error('Navigation requires a callback and an AbortSignal');
  }
  if (
    onFilePickerReady !== undefined &&
    (typeof onFilePickerReady !== 'function' || !signal)
  ) {
    throw new Error('File selection requires a callback and an AbortSignal');
  }
  origin(platformOrigin);
  if (
    !installationId ||
    typeof installationId !== 'string' ||
    installationId.length > 36
  ) {
    throw new Error('An installation ID is required');
  }
  const host =
    hostWindow ??
    (appWindow.parent !== appWindow ? appWindow.parent : appWindow.opener);
  if (
    !host ||
    host === appWindow ||
    platformOrigin === appWindow.location.origin
  ) {
    throw new Error('A separate, trusted platform host window is required');
  }
  if (signal?.aborted)
    throw signal.reason ?? new Error('App connection aborted');
  const verifier = base64url(webCrypto.getRandomValues(new Uint8Array(32)));
  const codeChallenge = base64url(
    await webCrypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(verifier),
    ),
  );
  const requestId = webCrypto.randomUUID();
  return new Promise((resolve, reject) => {
    let settled = false;
    let exchanging = false;
    let active = true;
    let context = null;
    let expiresAt = 0;
    let expiry;
    let hostCheck;
    let navigationEnabled = false;
    let filePickerEnabled = false;
    let filePicker = null;
    let navigationPending = null;
    const navigationRequests = [];
    const finishNavigation = (error, status) => {
      const pending = navigationPending;
      if (!pending) return;
      navigationPending = null;
      clearTimeout(pending.timer);
      if (error) pending.reject(error);
      else pending.resolve({ status });
    };
    const offerApp = async (target) => {
      const destination = navigationTarget(target);
      if (
        !active ||
        !navigationEnabled ||
        signal.aborted ||
        host.closed ||
        Date.now() >= expiresAt
      ) {
        return Promise.reject(new Error('App navigation connection is closed'));
      }
      if (navigationPending) return Promise.resolve({ status: 'busy' });
      const now = Date.now();
      while (navigationRequests.length && now - navigationRequests[0] >= 60000)
        navigationRequests.shift();
      if (navigationRequests.length >= 6)
        return Promise.resolve({ status: 'busy' });
      navigationRequests.push(now);
      return new Promise((resolveOffer, rejectOffer) => {
        const id = webCrypto.randomUUID();
        navigationPending = {
          id,
          resolve: resolveOffer,
          reject: rejectOffer,
          timer: setTimeout(
            () => finishNavigation(new Error('App navigation offer timed out')),
            10000,
          ),
        };
        try {
          host.postMessage(
            {
              type: 'miy.app.navigation.request',
              version: APP_PROTOCOL_VERSION,
              navigation_version: APP_NAVIGATION_VERSION,
              installation_id: installationId,
              request_id: requestId,
              navigation_id: id,
              target: destination,
            },
            platformOrigin,
          );
        } catch {
          finishNavigation(new Error('App navigation offer unavailable'));
        }
      });
    };
    const applyContext = () => {
      if (!active || signal?.aborted || !context || Date.now() >= expiresAt)
        return;
      try {
        onUIContext({ theme: context.theme, locale: context.locale });
      } catch {
        /* Presentation callbacks never change identity or authorization. */
      }
    };
    const clean = () => {
      active = false;
      filePicker?.close();
      appWindow.removeEventListener('message', receive);
      appWindow.removeEventListener('pagehide', leave);
      signal?.removeEventListener('abort', abort);
      clearTimeout(timer);
      clearInterval(retry);
      clearTimeout(expiry);
      clearInterval(hostCheck);
      finishNavigation(new Error('App navigation connection is closed'));
    };
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearInterval(retry);
      if (error) {
        clean();
        reject(error);
      } else {
        if (
          ((onUIContext && context) ||
            navigationEnabled ||
            filePickerEnabled) &&
          !signal.aborted
        ) {
          expiresAt = Date.parse(result.expires_at);
          expiry = setTimeout(
            clean,
            Math.min(expiresAt - Date.now(), 2147483647),
          );
          hostCheck = setInterval(() => {
            if (host.closed || Date.now() >= expiresAt) clean();
          }, 1000);
          if (filePickerEnabled) {
            filePicker = createFilePicker({
              host,
              platformOrigin,
              installationId,
              audience: appWindow.location.origin,
              requestId,
              session: result,
              signal,
              crypto: webCrypto,
              isCurrent: () => active && Date.now() < expiresAt,
            });
            try {
              onFilePickerReady({ selectFile: filePicker.selectFile });
            } catch {
              /* App callbacks do not change identity. */
            }
          }
          if (onUIContext && context) applyContext();
          if (navigationEnabled) {
            try {
              onNavigationReady(offerApp);
            } catch {
              /* App callbacks do not change identity. */
            }
          }
        } else clean();
        resolve(result);
      }
    };
    const abort = () => {
      if (settled) clean();
      else finish(signal.reason ?? new Error('App connection aborted'));
    };
    const leave = () => {
      if (settled) clean();
      else finish(new Error('App document left'));
    };
    const receive = async (event) => {
      const message = event.data;
      if (
        !active ||
        signal?.aborted ||
        event.source !== host ||
        event.origin !== platformOrigin ||
        !message ||
        message.version !== APP_PROTOCOL_VERSION ||
        message.installation_id !== installationId ||
        message.request_id !== requestId
      )
        return;
      if (message.type === 'miy.app.file-picker.result') {
        filePicker?.receive(message);
        return;
      }
      if (message.type === 'miy.app.navigation.result') {
        if (
          !settled ||
          !navigationEnabled ||
          Date.now() >= expiresAt ||
          message.navigation_version !== APP_NAVIGATION_VERSION ||
          message.navigation_id !== navigationPending?.id ||
          !['offered', 'busy', 'unavailable'].includes(message.status)
        )
          return;
        finishNavigation(null, message.status);
        return;
      }
      if (message.type === 'miy.app.context') {
        if (!context || !onUIContext) return;
        const next = uiContext(message.ui_context);
        if (!next || next.sequence <= context.sequence) return;
        context = next;
        if (settled) applyContext();
        return;
      }
      if (
        settled ||
        exchanging ||
        message.type !== 'miy.app.launch' ||
        typeof message.code !== 'string' ||
        !/^[A-Za-z0-9_-]{40,128}$/.test(message.code)
      )
        return;
      exchanging = true;
      context = onUIContext ? uiContext(message.ui_context) : null;
      navigationEnabled = Boolean(
        onNavigationReady &&
          message.navigation_version === APP_NAVIGATION_VERSION,
      );
      clearInterval(retry);
      try {
        const session = await exchange({
          installation_id: installationId,
          code: message.code,
          code_verifier: verifier,
        });
        if (
          !session ||
          session.installation_id !== installationId ||
          session.audience !== appWindow.location.origin ||
          typeof session.token !== 'string' ||
          !/^[A-Za-z0-9_-]{40,128}$/.test(session.token) ||
          !Number.isFinite(Date.parse(session.expires_at)) ||
          Date.parse(session.expires_at) <= Date.now()
        ) {
          throw new Error(
            'App session response does not match this installation',
          );
        }
        filePickerEnabled = Boolean(
          onFilePickerReady &&
            message.file_picker_version === APP_FILE_PICKER_VERSION &&
            Array.isArray(session.permissions) &&
            session.permissions.includes('identity:read') &&
            session.permissions.includes('files:read-selected'),
        );
        finish(null, session);
      } catch (error) {
        finish(error);
      }
    };
    const timer = setTimeout(
      () => finish(new Error('Platform handshake timed out')),
      timeoutMs,
    );
    const announce = () => {
      if (settled || exchanging) return;
      try {
        host.postMessage(
          {
            type: 'miy.app.ready',
            version: APP_PROTOCOL_VERSION,
            installation_id: installationId,
            request_id: requestId,
            code_challenge: codeChallenge,
            ...(onUIContext
              ? { ui_context_version: APP_UI_CONTEXT_VERSION }
              : {}),
            ...(onFilePickerReady
              ? { file_picker_version: APP_FILE_PICKER_VERSION }
              : {}),
            ...(onNavigationReady
              ? { navigation_version: APP_NAVIGATION_VERSION }
              : {}),
          },
          platformOrigin,
        );
      } catch (error) {
        finish(error);
      }
    };
    // A frame can announce just before its parent's load event. Retry the same
    // nonce so the host can recover that race without creating another intent.
    const retry = setInterval(announce, 500);
    appWindow.addEventListener('message', receive);
    appWindow.addEventListener('pagehide', leave);
    signal?.addEventListener('abort', abort, { once: true });
    // Digest calculation is async; observe cancellation again before issuing anything.
    if (signal?.aborted) {
      abort();
      return;
    }
    announce();
  });
}
