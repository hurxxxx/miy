/** Connection-scoped selected-file capability. No arbitrary URL or platform bearer. */
export const APP_FILE_PICKER_VERSION = 1;
const MAX_BYTES = 10485760;
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const TOKEN = /^[A-Za-z0-9_.-]{1,4096}$/;
const HASH = /^[0-9a-f]{64}$/;
const unavailable = () => new Error('Selected file access unavailable');
function discard(response) {
  void response.body?.cancel().catch(() => undefined);
  return unavailable();
}
const record = (value) =>
  value && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) =>
  record(value) &&
  Object.keys(value).length === keys.length &&
  keys.every((key) => Object.hasOwn(value, key));
// Core/JSON Schema count Unicode code points. Bound UTF-16 before allocating.
const fileText = (value) =>
  typeof value === 'string' &&
  value.length <= 510 &&
  Array.from(value).length <= 255;
const contextKeys = [
  'schema_version',
  'installation_id',
  'audience',
  'selection_id',
];
const validExpiry = (value) =>
  typeof value === 'string' &&
  /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
  Number.isFinite(Date.parse(value)) &&
  Date.parse(value) > Date.now();

function context(value, installationId, audience, selectionId) {
  return (
    value.schema_version === 1 &&
    value.installation_id === installationId &&
    value.audience === audience &&
    value.selection_id === selectionId &&
    UUID.test(value.selection_id)
  );
}
function proof(value, installationId, audience, selectionId) {
  return (
    exact(value, [
      ...contextKeys,
      'selection_request',
      'expires_at',
      'max_bytes',
    ]) &&
    context(value, installationId, audience, selectionId) &&
    typeof value.selection_request === 'string' &&
    TOKEN.test(value.selection_request) &&
    value.max_bytes === MAX_BYTES &&
    validExpiry(value.expires_at)
  );
}
function selected(value, installationId, audience, selectionId) {
  if (
    !exact(value, [...contextKeys, 'file', 'read_grant', 'expires_at']) ||
    !context(value, installationId, audience, selectionId) ||
    typeof value.read_grant !== 'string' ||
    !TOKEN.test(value.read_grant) ||
    !validExpiry(value.expires_at)
  )
    return false;
  const file = value.file;
  return (
    exact(file, ['file_id', 'name', 'content_type', 'size_bytes', 'version']) &&
    typeof file.file_id === 'string' &&
    UUID.test(file.file_id) &&
    fileText(file.name) &&
    fileText(file.content_type) &&
    Number.isSafeInteger(file.size_bytes) &&
    file.size_bytes >= 0 &&
    file.size_bytes <= MAX_BYTES &&
    typeof file.version === 'string' &&
    HASH.test(file.version)
  );
}

async function bounded(action, signals, timeoutMs) {
  const controller = new AbortController();
  let rejectAborted;
  const aborted = new Promise((_, reject) => {
    rejectAborted = reject;
  });
  const cancel = () => {
    controller.abort();
    rejectAborted(unavailable());
  };
  signals.forEach((signal) =>
    signal?.addEventListener('abort', cancel, { once: true }),
  );
  const timer = setTimeout(cancel, Math.max(0, timeoutMs));
  try {
    if (signals.some((signal) => signal?.aborted) || timeoutMs <= 0)
      throw unavailable();
    return await Promise.race([action(controller.signal), aborted]);
  } finally {
    clearTimeout(timer);
    signals.forEach((signal) => signal?.removeEventListener('abort', cancel));
    controller.abort();
  }
}

async function bodyBytes(response, maximum, signal, expectedSize) {
  if (
    !response.ok ||
    response.redirected ||
    (response.headers.get('content-encoding') &&
      response.headers.get('content-encoding') !== 'identity')
  )
    throw discard(response);
  const length = response.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > maximum))
    throw discard(response);
  if (
    expectedSize !== undefined &&
    (length === null || Number(length) !== expectedSize)
  )
    throw discard(response);
  if (!response.body) {
    if (expectedSize === 0 && length === '0') return new ArrayBuffer(0);
    throw unavailable();
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  const abort = () => {
    void reader.cancel().catch(() => undefined);
  };
  signal.addEventListener('abort', abort, { once: true });
  try {
    if (signal.aborted) throw unavailable();
    while (true) {
      const next = await reader.read();
      if (signal.aborted) throw unavailable();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > maximum || (expectedSize !== undefined && size > expectedSize))
        throw unavailable();
      chunks.push(next.value);
    }
    if (
      (expectedSize !== undefined && size !== expectedSize) ||
      (length !== null && Number(length) !== size)
    )
      throw unavailable();
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return bytes.buffer;
  } finally {
    signal.removeEventListener('abort', abort);
    void reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

export function createFilePicker({
  host,
  platformOrigin,
  installationId,
  audience,
  requestId,
  session: connectedSession,
  signal,
  crypto,
  isCurrent,
}) {
  // The returned session object belongs to the app; retain this connection's
  // verified credential and deadline independently of later caller mutations.
  const session = {
    token: connectedSession.token,
    expires_at: connectedSession.expires_at,
  };
  let active = true;
  let pending = null;
  let reading = false;
  const requests = [];
  const lifetime = new AbortController();
  const current = () =>
    active &&
    !signal.aborted &&
    !lifetime.signal.aborted &&
    !host.closed &&
    Date.now() < Date.parse(session.expires_at) &&
    isCurrent();
  const post = (type, extra) =>
    host.postMessage(
      {
        type,
        version: 1,
        file_picker_version: 1,
        installation_id: installationId,
        request_id: requestId,
        ...extra,
      },
      platformOrigin,
    );
  const finish = (result, cancelHost = false) => {
    const previous = pending;
    if (!previous) return;
    pending = null;
    clearTimeout(previous.timer);
    previous.controller.abort();
    if (cancelHost && previous.sent) {
      try {
        post('miy.app.file-picker.cancel', { selection_id: previous.id });
      } catch {
        /* Already unavailable. */
      }
    }
    previous.resolve(result);
  };
  const readSelected =
    (selection) =>
    async ({ signal: readSignal } = {}) => {
      if (
        !current() ||
        Date.now() >= Date.parse(selection.expires_at) ||
        reading
      )
        throw unavailable();
      reading = true;
      try {
        const result = await bounded(
          async (readAbort) => {
            const response = await fetch('/api/platform-files/content', {
              method: 'GET',
              credentials: 'omit',
              cache: 'no-store',
              redirect: 'error',
              headers: {
                Authorization: `Bearer ${session.token}`,
                'X-MIY-Selected-File': selection.read_grant,
              },
              signal: readAbort,
            });
            if (
              response.headers
                .get('content-type')
                ?.split(';')[0]
                .trim()
                .toLowerCase() !== 'application/octet-stream'
            )
              throw discard(response);
            return bodyBytes(
              response,
              MAX_BYTES,
              readAbort,
              selection.file.size_bytes,
            );
          },
          [signal, lifetime.signal, readSignal],
          Math.min(
            20000,
            Date.parse(selection.expires_at) - Date.now(),
            Date.parse(session.expires_at) - Date.now(),
          ),
        );
        if (!current() || Date.now() >= Date.parse(selection.expires_at))
          throw unavailable();
        return result;
      } catch {
        throw unavailable();
      } finally {
        reading = false;
      }
    };
  const receive = (message) => {
    if (
      !pending ||
      !current() ||
      message.file_picker_version !== 1 ||
      message.selection_id !== pending.id
    )
      return;
    const result = message.result;
    if (
      exact(result, ['status']) &&
      ['canceled', 'unavailable', 'busy'].includes(result.status)
    ) {
      finish({ status: result.status });
      return;
    }
    if (
      !exact(result, ['status', 'selection']) ||
      result.status !== 'selected' ||
      !selected(result.selection, installationId, audience, pending.id)
    ) {
      finish({ status: 'unavailable' }, true);
      return;
    }
    const selection = structuredClone(result.selection);
    const file = selection.file;
    finish({
      status: 'selected',
      file: {
        fileId: file.file_id,
        name: file.name,
        contentType: file.content_type,
        sizeBytes: file.size_bytes,
        version: file.version,
      },
      readGrant: selection.read_grant,
      expiresAt: selection.expires_at,
      read: readSelected(selection),
    });
  };
  const selectFile = (...args) => {
    if (args.length || !current())
      return Promise.resolve({ status: 'unavailable' });
    if (pending) return Promise.resolve({ status: 'busy' });
    const now = Date.now();
    while (requests.length && now - requests[0] >= 60000) requests.shift();
    if (requests.length >= 6) return Promise.resolve({ status: 'busy' });
    requests.push(now);
    const id = crypto.randomUUID();
    return new Promise((resolve) => {
      const attempt = {
        id,
        resolve,
        controller: new AbortController(),
        sent: false,
        timer: null,
      };
      pending = attempt;
      void bounded(
        async (requestAbort) => {
          const response = await fetch(
            '/api/platform-files/selection-request',
            {
              method: 'POST',
              credentials: 'omit',
              cache: 'no-store',
              redirect: 'error',
              headers: {
                Authorization: `Bearer ${session.token}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ schema_version: 1, selection_id: id }),
              signal: requestAbort,
            },
          );
          if (
            response.headers
              .get('content-type')
              ?.split(';')[0]
              .trim()
              .toLowerCase() !== 'application/json'
          )
            throw discard(response);
          return JSON.parse(
            new TextDecoder('utf-8', { fatal: true }).decode(
              await bodyBytes(response, 16384, requestAbort),
            ),
          );
        },
        [signal, lifetime.signal, attempt.controller.signal],
        5000,
      )
        .then((selection) => {
          if (pending !== attempt || !current()) return;
          if (!proof(selection, installationId, audience, id)) {
            finish({ status: 'unavailable' });
            return;
          }
          const duration = Math.min(
            60000,
            Date.parse(selection.expires_at) - Date.now(),
            Date.parse(session.expires_at) - Date.now(),
          );
          attempt.timer = setTimeout(() => {
            if (pending === attempt) finish({ status: 'unavailable' }, true);
          }, duration);
          attempt.sent = true;
          post('miy.app.file-picker.request', { selection });
        })
        .catch(() => {
          if (pending === attempt) finish({ status: 'unavailable' }, true);
        });
    });
  };
  const close = () => {
    active = false;
    finish({ status: 'unavailable' }, true);
    lifetime.abort();
  };
  return { selectFile, receive, close };
}
