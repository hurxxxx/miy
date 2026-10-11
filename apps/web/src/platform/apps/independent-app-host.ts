import type { IndependentLaunch } from './independent-apps-api';

export const INDEPENDENT_APP_ROUTE = '/apps/:appId/installed/:installationId';

export interface IndependentUIContext {
  theme: 'light' | 'dark';
  locale: string;
}

export interface IndependentNavigationTarget {
  app_id: string;
  installation_id?: string;
}
export type IndependentNavigationStatus = 'offered' | 'busy' | 'unavailable';
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

export interface IndependentFileSelectionMetadata {
  file_id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  version: string;
}
interface IndependentFileSelectionContext {
  schema_version: 1;
  installation_id: string;
  audience: string;
  selection_id: string;
}
export interface IndependentFileSelectionRequest
  extends IndependentFileSelectionContext {
  selection_request: string;
  expires_at: string;
  max_bytes: 10485760;
}
export interface IndependentSelectedFile
  extends IndependentFileSelectionContext {
  file: IndependentFileSelectionMetadata;
  read_grant: string;
  expires_at: string;
}
export type IndependentFileSelectionResult =
  | { status: 'selected'; selection: IndependentSelectedFile }
  | { status: 'canceled' | 'unavailable' | 'busy' };
const fileContextKeys = [
  'schema_version',
  'installation_id',
  'audience',
  'selection_id',
];
function exactFileRecord(
  value: unknown,
  keys: string[],
): value is Record<string, unknown> {
  return Boolean(
    value &&
      typeof value === 'object' &&
      !Array.isArray(value) &&
      Object.keys(value).length === keys.length &&
      keys.every((key) => Object.hasOwn(value, key)),
  );
}
function fileExpiry(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    Date.parse(value) > Date.now()
  );
}
function fileToken(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9_.-]{1,4096}$/.test(value);
}
function fileText(value: unknown): value is string {
  // Core/JSON Schema count code points; the first bound limits allocation.
  return (
    typeof value === 'string' &&
    value.length <= 510 &&
    Array.from(value).length <= 255
  );
}
export function checkedIndependentFileMetadata(
  value: unknown,
): IndependentFileSelectionMetadata | null {
  if (
    !exactFileRecord(value, [
      'file_id',
      'name',
      'content_type',
      'size_bytes',
      'version',
    ]) ||
    typeof value.file_id !== 'string' ||
    !uuid.test(value.file_id) ||
    !fileText(value.name) ||
    !fileText(value.content_type) ||
    !Number.isSafeInteger(value.size_bytes) ||
    typeof value.size_bytes !== 'number' ||
    value.size_bytes < 0 ||
    value.size_bytes > 10485760 ||
    typeof value.version !== 'string' ||
    !/^[0-9a-f]{64}$/.test(value.version)
  )
    return null;
  return {
    file_id: value.file_id,
    name: value.name,
    content_type: value.content_type,
    size_bytes: value.size_bytes,
    version: value.version,
  };
}
export function checkedIndependentFileSelectionRequest(
  value: unknown,
  installationId: string,
  audience: string,
): IndependentFileSelectionRequest | null {
  if (
    !exactFileRecord(value, [
      ...fileContextKeys,
      'selection_request',
      'expires_at',
      'max_bytes',
    ]) ||
    value.schema_version !== 1 ||
    value.installation_id !== installationId ||
    !uuid.test(installationId) ||
    value.audience !== audience ||
    typeof value.selection_id !== 'string' ||
    !uuid.test(value.selection_id) ||
    !fileToken(value.selection_request) ||
    !fileExpiry(value.expires_at) ||
    value.max_bytes !== 10485760
  )
    return null;
  return {
    schema_version: 1,
    installation_id: installationId,
    audience,
    selection_id: value.selection_id,
    selection_request: value.selection_request,
    expires_at: value.expires_at,
    max_bytes: 10485760,
  };
}
export function checkedIndependentSelectedFile(
  value: unknown,
  request: IndependentFileSelectionRequest,
): IndependentSelectedFile | null {
  if (
    !exactFileRecord(value, [
      ...fileContextKeys,
      'file',
      'read_grant',
      'expires_at',
    ]) ||
    value.schema_version !== 1 ||
    value.installation_id !== request.installation_id ||
    value.audience !== request.audience ||
    value.selection_id !== request.selection_id ||
    !fileToken(value.read_grant) ||
    !fileExpiry(value.expires_at)
  )
    return null;
  const file = checkedIndependentFileMetadata(value.file);
  if (!file) return null;
  return {
    schema_version: 1,
    installation_id: request.installation_id,
    audience: request.audience,
    selection_id: request.selection_id,
    file,
    read_grant: value.read_grant,
    expires_at: value.expires_at,
  };
}

export function checkedNavigationTarget(
  value: unknown,
): IndependentNavigationTarget | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const target = value as Record<string, unknown>;
  if (
    Object.keys(target).some(
      (key) => !['app_id', 'installation_id'].includes(key),
    ) ||
    typeof target.app_id !== 'string' ||
    !/^[a-z][a-z0-9-]{1,63}$/.test(target.app_id) ||
    (target.installation_id !== undefined &&
      (typeof target.installation_id !== 'string' ||
        !uuid.test(target.installation_id)))
  )
    return null;
  return {
    app_id: target.app_id,
    ...(typeof target.installation_id === 'string'
      ? { installation_id: target.installation_id }
      : {}),
  };
}

function checkedUIContext(value: IndependentUIContext | undefined) {
  if (
    !value ||
    !['light', 'dark'].includes(value.theme) ||
    typeof value.locale !== 'string' ||
    value.locale.length > 35 ||
    !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(value.locale)
  )
    return null;
  return { theme: value.theme, locale: value.locale };
}

export function independentAppPath(appId: string, installationId: string) {
  return `/apps/${encodeURIComponent(appId)}/installed/${encodeURIComponent(installationId)}`;
}

export function independentAppOrigin(
  value: string,
  platformOrigin: string,
): string | null {
  try {
    const url = new URL(value);
    if (
      url.origin !== value ||
      value === platformOrigin ||
      url.username ||
      url.password ||
      (url.protocol !== 'https:' &&
        !(
          url.protocol === 'http:' &&
          ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
        ))
    )
      return null;
    return url.origin;
  } catch {
    return null;
  }
}

/** Fresh nonces renew sessions; repeats never issue concurrent or duplicate codes. */
export function listenForIndependentApp({
  host = window,
  frame,
  origin,
  installationId,
  signal,
  issueLaunch,
  onConnected,
  onFailure,
  getUIContext,
  offerNavigation,
  selectFile,
}: {
  host?: Window;
  frame: Window;
  origin: string;
  installationId: string;
  signal: AbortSignal;
  issueLaunch: (
    challenge: string,
    signal: AbortSignal,
  ) => Promise<IndependentLaunch>;
  onConnected: () => void;
  onFailure: () => void;
  getUIContext?: () => IndependentUIContext;
  selectFile?: (
    request: IndependentFileSelectionRequest,
    signal: AbortSignal,
    isCurrent: () => boolean,
  ) => Promise<IndependentFileSelectionResult>;
  offerNavigation?: (
    target: IndependentNavigationTarget,
    signal: AbortSignal,
    isCurrent: () => boolean,
  ) => Promise<IndependentNavigationStatus>;
}) {
  const recent = new Map<string, number>();
  const windowMs = 60000;
  const maxLaunches = 6;
  let pending: AbortController | null = null;
  let limited = false;
  let closed = false;
  let navigationChannel: {
    requestId: string;
    expiresAt: number;
    controller: AbortController;
  } | null = null;
  let navigationPending = false;
  const navigationRecent = new Map<string, number>();
  const clearNavigation = () => {
    navigationChannel?.controller.abort();
    navigationChannel = null;
  };
  const receiveNavigation = async (data: Record<string, unknown>) => {
    const channel = navigationChannel;
    if (
      !channel ||
      !offerNavigation ||
      data.navigation_version !== 1 ||
      data.request_id !== channel.requestId ||
      typeof data.navigation_id !== 'string' ||
      !uuid.test(data.navigation_id) ||
      channel.controller.signal.aborted
    )
      return;
    if (frame.closed || Date.now() >= channel.expiresAt) {
      clearNavigation();
      return;
    }
    const target = checkedNavigationTarget(data.target);
    if (!target) return;
    const now = Date.now();
    for (const [id, time] of navigationRecent)
      if (now - time >= 60000) navigationRecent.delete(id);
    if (navigationRecent.has(data.navigation_id)) return;
    // A malformed or flooding app never grows memory or launches additional reads.
    if (navigationPending || navigationRecent.size >= 6) return;
    navigationRecent.set(data.navigation_id, now);
    navigationPending = true;
    const deadline = globalThis.setTimeout(
      () => channel.controller.abort(),
      9000,
    );
    let rejectCancelled!: () => void;
    const cancelled = new Promise<never>((_, reject) => {
      rejectCancelled = () => reject(new Error('navigation-cancelled'));
      channel.controller.signal.addEventListener('abort', rejectCancelled, {
        once: true,
      });
    });
    try {
      const status = await Promise.race([
        offerNavigation(
          target,
          channel.controller.signal,
          () =>
            !closed &&
            !signal.aborted &&
            navigationChannel === channel &&
            !channel.controller.signal.aborted &&
            !frame.closed &&
            Date.now() < channel.expiresAt,
        ),
        cancelled,
      ]);
      if (
        closed ||
        signal.aborted ||
        channel !== navigationChannel ||
        channel.controller.signal.aborted ||
        frame.closed
      )
        return;
      frame.postMessage(
        {
          type: 'miy.app.navigation.result',
          version: 1,
          navigation_version: 1,
          installation_id: installationId,
          request_id: channel.requestId,
          navigation_id: data.navigation_id,
          status,
        },
        origin,
      );
    } catch {
      /* Timeout closes only the optional navigation channel. */
    } finally {
      globalThis.clearTimeout(deadline);
      channel.controller.signal.removeEventListener('abort', rejectCancelled);
      navigationPending = false;
    }
  };
  let fileChannel: {
    requestId: string;
    expiresAt: number;
    controller: AbortController;
  } | null = null;
  let filePending: { id: string; controller: AbortController } | null = null;
  const fileRecent = new Map<string, number>();
  const clearFiles = () => {
    fileChannel?.controller.abort();
    fileChannel = null;
    filePending?.controller.abort();
  };
  const receiveFileSelection = async (data: Record<string, unknown>) => {
    const channel = fileChannel;
    if (
      !channel ||
      !selectFile ||
      data.file_picker_version !== 1 ||
      data.request_id !== channel.requestId ||
      channel.controller.signal.aborted
    )
      return;
    if (frame.closed || Date.now() >= channel.expiresAt) {
      clearFiles();
      return;
    }
    if (data.type === 'miy.app.file-picker.cancel') {
      if (data.selection_id === filePending?.id)
        filePending?.controller.abort();
      return;
    }
    const request = checkedIndependentFileSelectionRequest(
      data.selection,
      installationId,
      origin,
    );
    if (!request) return;
    const now = Date.now();
    for (const [id, time] of fileRecent)
      if (now - time >= 60000) fileRecent.delete(id);
    if (fileRecent.has(request.selection_id) || fileRecent.size >= 6) return;
    fileRecent.set(request.selection_id, now);
    const send = (result: IndependentFileSelectionResult) =>
      frame.postMessage(
        {
          type: 'miy.app.file-picker.result',
          version: 1,
          file_picker_version: 1,
          installation_id: installationId,
          request_id: channel.requestId,
          selection_id: request.selection_id,
          result,
        },
        origin,
      );
    if (filePending) {
      send({ status: 'busy' });
      return;
    }
    const attempt = {
      id: request.selection_id,
      controller: new AbortController(),
    };
    filePending = attempt;
    const isCurrent = () =>
      !closed &&
      !signal.aborted &&
      fileChannel === channel &&
      !channel.controller.signal.aborted &&
      filePending === attempt &&
      !attempt.controller.signal.aborted &&
      !frame.closed &&
      Date.now() < channel.expiresAt &&
      Date.now() < Date.parse(request.expires_at);
    const cancel = () => attempt.controller.abort();
    channel.controller.signal.addEventListener('abort', cancel, { once: true });
    const deadline = globalThis.setTimeout(
      cancel,
      Math.min(
        60000,
        Date.parse(request.expires_at) - now,
        channel.expiresAt - now,
      ),
    );
    let rejectCancelled!: () => void;
    const cancelled = new Promise<never>((_, reject) => {
      rejectCancelled = () => reject(new Error('file-selection-cancelled'));
      attempt.controller.signal.addEventListener('abort', rejectCancelled, {
        once: true,
      });
    });
    try {
      const result = await Promise.race([
        selectFile(request, attempt.controller.signal, isCurrent),
        cancelled,
      ]);
      if (!isCurrent()) return;
      if (
        exactFileRecord(result, ['status', 'selection']) &&
        result.status === 'selected'
      ) {
        const selection = checkedIndependentSelectedFile(
          result.selection,
          request,
        );
        send(
          selection
            ? { status: 'selected', selection }
            : { status: 'unavailable' },
        );
      } else if (
        exactFileRecord(result, ['status']) &&
        ['canceled', 'unavailable', 'busy'].includes(String(result.status))
      ) {
        send({ status: result.status as 'canceled' | 'unavailable' | 'busy' });
      } else send({ status: 'unavailable' });
    } catch {
      if (isCurrent()) send({ status: 'unavailable' });
    } finally {
      globalThis.clearTimeout(deadline);
      channel.controller.signal.removeEventListener('abort', cancel);
      attempt.controller.signal.removeEventListener('abort', rejectCancelled);
      attempt.controller.abort();
      if (filePending === attempt) filePending = null;
    }
  };
  let contextChannel: {
    requestId: string;
    sequence: number;
    value: IndependentUIContext;
  } | null = null;
  const updateUIContext = () => {
    if (closed || signal.aborted || !contextChannel) return;
    if (frame.closed) {
      contextChannel = null;
      return;
    }
    const value = checkedUIContext(getUIContext?.());
    if (
      !value ||
      (value.theme === contextChannel.value.theme &&
        value.locale === contextChannel.value.locale)
    )
      return;
    if (contextChannel.sequence >= Number.MAX_SAFE_INTEGER) {
      contextChannel = null;
      return;
    }
    contextChannel.sequence += 1;
    contextChannel.value = value;
    try {
      frame.postMessage(
        {
          type: 'miy.app.context',
          version: 1,
          installation_id: installationId,
          request_id: contextChannel.requestId,
          ui_context: {
            version: 1,
            sequence: contextChannel.sequence,
            ...value,
          },
        },
        origin,
      );
    } catch {
      contextChannel = null;
    }
  };
  const receive = async (event: MessageEvent) => {
    const data = event.data;
    if (
      signal.aborted ||
      closed ||
      event.source !== frame ||
      event.origin !== origin ||
      !data ||
      data.version !== 1 ||
      data.installation_id !== installationId
    )
      return;
    if (
      data.type === 'miy.app.file-picker.request' ||
      data.type === 'miy.app.file-picker.cancel'
    ) {
      await receiveFileSelection(data);
      return;
    }
    if (data.type === 'miy.app.navigation.request') {
      await receiveNavigation(data);
      return;
    }
    if (
      pending ||
      data.type !== 'miy.app.ready' ||
      typeof data.request_id !== 'string' ||
      !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(data.request_id) ||
      typeof data.code_challenge !== 'string' ||
      !/^[A-Za-z0-9_-]{43}$/.test(data.code_challenge)
    )
      return;
    const now = Date.now();
    for (const [nonce, started] of recent) {
      if (now - started >= windowMs) recent.delete(nonce);
    }
    if (recent.has(data.request_id)) return;
    if (recent.size >= maxLaunches) {
      if (!limited) onFailure();
      limited = true;
      return;
    }
    recent.set(data.request_id, now);
    contextChannel = null;
    clearNavigation();
    clearFiles();
    limited = false;
    const request = new AbortController();
    pending = request;
    const cancel = () => request.abort();
    signal.addEventListener('abort', cancel, { once: true });
    let rejectCancelled!: () => void;
    const cancelled = new Promise<never>((_, reject) => {
      rejectCancelled = () =>
        reject(new Error('independent-app-launch-cancelled'));
      request.signal.addEventListener('abort', rejectCancelled, { once: true });
    });
    const deadline = globalThis.setTimeout(cancel, 10000);
    try {
      const launch = await Promise.race([
        issueLaunch(data.code_challenge, request.signal),
        cancelled,
      ]);
      if (signal.aborted || request.signal.aborted || closed) return;
      if (
        launch.app_origin !== origin ||
        !/^[A-Za-z0-9_-]{40,128}$/.test(launch.code) ||
        typeof launch.expires_at !== 'string' ||
        !Number.isFinite(Date.parse(launch.expires_at)) ||
        Date.parse(launch.expires_at) <= Date.now()
      ) {
        throw new Error('independent-app-launch-invalid');
      }
      const context =
        data.ui_context_version === 1
          ? checkedUIContext(getUIContext?.())
          : null;
      frame.postMessage(
        {
          type: 'miy.app.launch',
          version: 1,
          installation_id: installationId,
          request_id: data.request_id,
          code: launch.code,
          expires_at: launch.expires_at,
          ...(selectFile && data.file_picker_version === 1
            ? { file_picker_version: 1 }
            : {}),
          ...(offerNavigation && data.navigation_version === 1
            ? { navigation_version: 1 }
            : {}),
          ...(context
            ? { ui_context: { version: 1, sequence: 0, ...context } }
            : {}),
        },
        origin,
      );
      if (context)
        contextChannel = {
          requestId: data.request_id,
          sequence: 0,
          value: context,
        };
      if (offerNavigation && data.navigation_version === 1)
        navigationChannel = {
          requestId: data.request_id,
          expiresAt: Date.now() + 300000,
          controller: new AbortController(),
        };
      if (selectFile && data.file_picker_version === 1)
        fileChannel = {
          requestId: data.request_id,
          expiresAt: Date.now() + 300000,
          controller: new AbortController(),
        };
      onConnected();
    } catch {
      if (!signal.aborted && !closed) onFailure();
    } finally {
      globalThis.clearTimeout(deadline);
      signal.removeEventListener('abort', cancel);
      request.signal.removeEventListener('abort', rejectCancelled);
      pending = null;
    }
  };
  host.addEventListener('message', receive);
  const navigationExpiry =
    offerNavigation || selectFile
      ? globalThis.setInterval(() => {
          if (
            navigationChannel &&
            (frame.closed || Date.now() >= navigationChannel.expiresAt)
          )
            clearNavigation();
          if (
            fileChannel &&
            (frame.closed || Date.now() >= fileChannel.expiresAt)
          )
            clearFiles();
        }, 1000)
      : undefined;
  const cleanup = () => {
    closed = true;
    contextChannel = null;
    clearNavigation();
    navigationRecent.clear();
    clearFiles();
    fileRecent.clear();
    globalThis.clearInterval(navigationExpiry);
    pending?.abort();
    recent.clear();
    host.removeEventListener('message', receive);
  };
  signal.addEventListener('abort', cleanup, { once: true });
  if (signal.aborted) cleanup();
  const dispose = () => {
    cleanup();
    signal.removeEventListener('abort', cleanup);
  };
  return Object.assign(dispose, { updateUIContext });
}
