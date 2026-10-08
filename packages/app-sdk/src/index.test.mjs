import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { getEventListeners } from 'node:events';
import test from 'node:test';
import { connectApp } from './index.mjs';

function fixture(installationId = 'test-install') {
  let ready;
  let notify;
  const messages = [];
  const sent = new Promise((resolve) => {
    notify = resolve;
  });
  const appWindow = new EventTarget();
  const host = {
    postMessage(message, targetOrigin) {
      ready = message;
      messages.push(message);
      assert.equal(targetOrigin, 'https://platform.test');
      notify();
    },
  };
  appWindow.location = { origin: 'https://app.test' };
  appWindow.parent = host;
  const send = (
    overrides = {},
    source = host,
    origin = 'https://platform.test',
  ) => {
    const event = new Event('message');
    Object.assign(event, {
      source,
      origin,
      data: {
        type: 'miy.app.launch',
        version: 1,
        installation_id: installationId,
        request_id: ready.request_id,
        code: 'c'.repeat(43),
        ...overrides,
      },
    });
    appWindow.dispatchEvent(event);
  };
  const session = {
    token: 's'.repeat(43),
    installation_id: installationId,
    audience: appWindow.location.origin,
    expires_at: new Date(Date.now() + 10000).toISOString(),
  };
  return {
    appWindow,
    host,
    sent,
    send,
    session,
    messages,
    options: {
      platformOrigin: 'https://platform.test',
      installationId,
      window: appWindow,
      crypto: webcrypto,
      timeoutMs: 1000,
    },
  };
}

test('handshake binds origin, source, version, request and installation before exchanging', async () => {
  const f = fixture();
  let exchanges = 0;
  const connected = connectApp({
    ...f.options,
    exchange: async (payload) => {
      exchanges += 1;
      assert.equal(payload.code_verifier.length, 43);
      return f.session;
    },
  });
  await f.sent;
  f.send({}, {}, 'https://platform.test');
  f.send({}, f.host, 'https://attacker.test');
  f.send({ version: 2 });
  f.send({ request_id: 'old-frame-request' });
  f.send({ installation_id: 'other-install' });
  f.send({ code: 'invalid' });
  assert.equal(exchanges, 0);
  f.send();
  f.send();
  assert.deepEqual(await connected, f.session);
  assert.equal(exchanges, 1);
});

test('different audience, abort and missing host fail without leaking credentials', async () => {
  const f = fixture();
  const connected = connectApp({
    ...f.options,
    exchange: async () => ({ ...f.session, audience: 'https://wrong.test' }),
  });
  await f.sent;
  f.send();
  await assert.rejects(connected, /does not match/);
  const controller = new AbortController();
  controller.abort(new Error('cancelled'));
  await assert.rejects(
    connectApp({ ...f.options, signal: controller.signal }),
    /cancelled/,
  );
  await assert.rejects(
    connectApp({ ...f.options, platformOrigin: 'https://platform.test/path' }),
    /exact HTTPS origin/,
  );
  await assert.rejects(
    connectApp({ ...f.options, hostWindow: f.appWindow }),
    /separate/,
  );
});

test('a disconnected frame times out and cannot exchange a late response', async () => {
  const f = fixture();
  let exchanges = 0;
  const connected = connectApp({
    ...f.options,
    timeoutMs: 10,
    exchange: async () => {
      exchanges++;
      return f.session;
    },
  });
  await f.sent;
  await assert.rejects(connected, /timed out/);
  f.send();
  assert.equal(exchanges, 0);
});

test('load-race retries reuse the same nonce and stop once a launch is received', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  const f = fixture();
  const connected = connectApp({
    ...f.options,
    timeoutMs: 5000,
    exchange: async () => f.session,
  });
  await f.sent;
  t.mock.timers.tick(500);
  assert.equal(f.messages.length, 2);
  assert.deepEqual(f.messages[0], f.messages[1]);
  f.send();
  await connected;
  t.mock.timers.tick(1000);
  assert.equal(f.messages.length, 2);
});

const context = (sequence = 0, theme = 'dark', locale = 'en-US') => ({
  version: 1,
  sequence,
  theme,
  locale,
});

test('UI context is optional and opt-in requires an explicit lifetime', async () => {
  const f = fixture();
  await assert.rejects(
    connectApp({ ...f.options, onUIContext() {} }),
    /AbortSignal/,
  );
  const connected = connectApp({
    ...f.options,
    exchange: async () => f.session,
  });
  await f.sent;
  assert.equal(f.messages[0].ui_context_version, undefined);
  f.send({ ui_context: context() });
  assert.deepEqual(await connected, f.session);
  assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
});

test('new caller remains identity-compatible with an old host and invalid optional context', async () => {
  for (const value of [
    undefined,
    null,
    { ...context(), version: 2 },
    { ...context(), sequence: -1 },
  ]) {
    const f = fixture();
    const controller = new AbortController();
    let calls = 0;
    const connected = connectApp({
      ...f.options,
      signal: controller.signal,
      onUIContext() {
        calls++;
      },
      exchange: async () => f.session,
    });
    await f.sent;
    assert.equal(f.messages[0].ui_context_version, 1);
    f.send({ ui_context: value });
    assert.deepEqual(await connected, f.session);
    f.send({ type: 'miy.app.context', ui_context: context(1) });
    assert.equal(calls, 0);
    assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
  }
});

test('buffers only the newest UI context until the app session is validated', async (t) => {
  const f = fixture();
  const controller = new AbortController();
  t.after(() => controller.abort());
  const received = [];
  let exchange;
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onUIContext: (value) => received.push(value),
    exchange: () =>
      new Promise((resolve) => {
        exchange = resolve;
      }),
  });
  await f.sent;
  // No initial negotiation yet: unsolicited updates cannot create a channel.
  f.send({ type: 'miy.app.context', ui_context: context(100) });
  f.send({ ui_context: context() });
  f.send({ type: 'miy.app.context', ui_context: context(2, 'light', 'ko-KR') });
  f.send({ type: 'miy.app.context', ui_context: context(1) });
  assert.deepEqual(received, []);
  exchange(f.session);
  assert.deepEqual(await connected, f.session);
  assert.deepEqual(received, [{ theme: 'light', locale: 'ko-KR' }]);
  f.send({
    type: 'miy.app.context',
    ui_context: { ...context(3), token: 'must-not-forward' },
  });
  assert.deepEqual(received[1], { theme: 'dark', locale: 'en-US' });
});

test('invalid exchange never applies buffered presentation context', async () => {
  const f = fixture();
  const controller = new AbortController();
  let calls = 0;
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onUIContext() {
      calls++;
    },
    exchange: async () => ({ ...f.session, audience: 'https://wrong.test' }),
  });
  await f.sent;
  f.send({ ui_context: context() });
  await assert.rejects(connected, /does not match/);
  assert.equal(calls, 0);
  assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
});

test('UI updates pin source, origin, installation, nonce, versions and increasing sequence', async (t) => {
  const f = fixture();
  const controller = new AbortController();
  t.after(() => controller.abort());
  const received = [];
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onUIContext: (value) => received.push(value),
    exchange: async () => f.session,
  });
  await f.sent;
  f.send({ ui_context: context() });
  await connected;
  const update = { type: 'miy.app.context', ui_context: context(1, 'light') };
  f.send(update, {}, 'https://platform.test');
  f.send(update, f.host, 'https://other.test');
  for (const changed of [
    { installation_id: 'other' },
    { request_id: 'old' },
    { version: 2 },
    { ui_context: context(0) },
    { ui_context: context(-1) },
    { ui_context: context(1.5) },
    { ui_context: context(Number.MAX_SAFE_INTEGER + 1) },
    { ui_context: { ...context(1), version: 2 } },
    { ui_context: context(1, 'system') },
    { ui_context: context(1, 'light', 'x'.repeat(100)) },
    { ui_context: context(1, 'light', '<script>') },
  ])
    f.send({ ...update, ...changed });
  assert.equal(received.length, 1);
  f.send(update);
  f.send(update);
  assert.deepEqual(received, [
    { theme: 'dark', locale: 'en-US' },
    { theme: 'light', locale: 'en-US' },
  ]);
  assert.equal(f.messages.length, 1);
});

for (const boundary of ['abort', 'expiry', 'host-close', 'pagehide']) {
  test(`UI listeners stop after ${boundary}, leaving the last value to the app`, async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
    const f = fixture();
    const controller = new AbortController();
    t.after(() => controller.abort());
    let calls = 0;
    const connected = connectApp({
      ...f.options,
      signal: controller.signal,
      onUIContext() {
        calls++;
      },
      exchange: async () => f.session,
    });
    await f.sent;
    f.send({ ui_context: context() });
    await connected;
    assert.equal(calls, 1);
    if (boundary === 'abort') controller.abort();
    if (boundary === 'expiry') t.mock.timers.tick(10001);
    if (boundary === 'host-close') {
      f.host.closed = true;
      t.mock.timers.tick(1000);
    }
    if (boundary === 'pagehide')
      f.appWindow.dispatchEvent(new Event('pagehide'));
    f.send({ type: 'miy.app.context', ui_context: context(1, 'light') });
    assert.equal(calls, 1);
    assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
    assert.equal(getEventListeners(f.appWindow, 'pagehide').length, 0);
    assert.equal(getEventListeners(controller.signal, 'abort').length, 0);
  });
}

test('a presentation callback failure does not invalidate the app session', async (t) => {
  const f = fixture();
  const controller = new AbortController();
  t.after(() => controller.abort());
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onUIContext() {
      throw new Error('App rendering failed');
    },
    exchange: async () => f.session,
  });
  await f.sent;
  f.send({ ui_context: context() });
  assert.deepEqual(await connected, f.session);
});

async function navigationFixture(version = 1) {
  const f = fixture();
  const controller = new AbortController();
  let offer;
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onNavigationReady(value) {
      offer = value;
    },
    exchange: async () => f.session,
  });
  await f.sent;
  assert.equal(f.messages[0].navigation_version, 1);
  f.send({ navigation_version: version });
  assert.deepEqual(await connected, f.session);
  return { ...f, controller, offer };
}

test('navigation requires lifetime and keeps old hosts identity compatible', async () => {
  await assert.rejects(
    connectApp({ ...fixture().options, onNavigationReady() {} }),
    /AbortSignal/,
  );
  for (const version of [null, 2]) {
    const f = await navigationFixture(version);
    assert.equal(f.offer, undefined);
    assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
    f.controller.abort();
  }
});

test('navigation carries only bounded identifiers and accepts an exact correlated host offer', async () => {
  const f = await navigationFixture();
  try {
    const offered = f.offer({ appId: 'planner' });
    const request = f.messages.at(-1);
    assert.deepEqual(Object.keys(request).sort(), [
      'installation_id',
      'navigation_id',
      'navigation_version',
      'request_id',
      'target',
      'type',
      'version',
    ]);
    assert.deepEqual(request.target, { app_id: 'planner' });
    assert.deepEqual(await f.offer({ appId: 'files' }), { status: 'busy' });
    const response = {
      type: 'miy.app.navigation.result',
      navigation_version: 1,
      navigation_id: request.navigation_id,
      status: 'offered',
    };
    let finished = false;
    offered.then(() => {
      finished = true;
    });
    f.send(response, {}, 'https://platform.test');
    f.send(response, f.host, 'https://evil.test');
    f.send({ ...response, request_id: 'old' });
    f.send({ ...response, navigation_id: 'old' });
    f.send({ ...response, navigation_version: 2 });
    await Promise.resolve();
    assert.equal(finished, false);
    f.send(response);
    assert.deepEqual(await offered, { status: 'offered' });
    for (const bad of [
      { appId: '//evil' },
      { appId: 'files', path: '/' },
      { appId: 'files', installationId: 'anything' },
    ]) {
      await assert.rejects(f.offer(bad), /bounded app ID/);
    }
  } finally {
    f.controller.abort();
  }
});

test('navigation is bounded to six requests and abort invalidates retained functions', async () => {
  const f = await navigationFixture();
  for (let index = 0; index < 6; index++) {
    const pending = f.offer({ appId: 'files' });
    const request = f.messages.at(-1);
    f.send({
      type: 'miy.app.navigation.result',
      navigation_version: 1,
      navigation_id: request.navigation_id,
      status: 'unavailable',
    });
    assert.deepEqual(await pending, { status: 'unavailable' });
  }
  assert.deepEqual(await f.offer({ appId: 'files' }), { status: 'busy' });
  f.controller.abort();
  await assert.rejects(f.offer({ appId: 'files' }), /closed/);
  assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
});

test('pending navigation times out; host close and document leave remove its lifetime', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  const f = await navigationFixture();
  const pending = f.offer({ appId: 'files' });
  const rejected = assert.rejects(pending, /timed out|closed/);
  t.mock.timers.tick(10000);
  await rejected;
  f.controller.abort();
  const next = await navigationFixture();
  const active = next.offer({ appId: 'files' });
  const cancelled = assert.rejects(active, /closed/);
  next.host.closed = true;
  t.mock.timers.tick(1000);
  await cancelled;
  await assert.rejects(next.offer({ appId: 'files' }), /closed/);
  next.controller.abort();
});

test('navigation callback is unavailable until session validation and never exposed by a cancelled or invalid exchange', async () => {
  for (const outcome of ['valid', 'invalid', 'aborted']) {
    const f = fixture();
    const controller = new AbortController();
    let callbacks = 0;
    let complete;
    const connected = connectApp({
      ...f.options,
      signal: controller.signal,
      onNavigationReady() {
        callbacks++;
      },
      exchange: () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    });
    await f.sent;
    f.send({ navigation_version: 1 });
    assert.equal(callbacks, 0);
    const rejected = outcome === 'valid' ? null : assert.rejects(connected);
    if (outcome === 'aborted') controller.abort();
    complete(
      outcome === 'invalid'
        ? { ...f.session, audience: 'https://other.test' }
        : f.session,
    );
    if (rejected) await rejected;
    else assert.deepEqual(await connected, f.session);
    assert.equal(callbacks, outcome === 'valid' ? 1 : 0);
    controller.abort();
  }
});

const fileInstall = '82345678-1234-4321-8765-123456789abc';
const fileId = '92345678-1234-4321-8765-123456789abc';
const proofFor = (selectionId) => ({
  schema_version: 1,
  installation_id: fileInstall,
  audience: 'https://app.test',
  selection_id: selectionId,
  selection_request: 'request-proof',
  expires_at: new Date(Date.now() + 60000).toISOString(),
  max_bytes: 10485760,
});
const selectedFor = (selectionId) => ({
  schema_version: 1,
  installation_id: fileInstall,
  audience: 'https://app.test',
  selection_id: selectionId,
  file: {
    file_id: fileId,
    name: 'synthetic.txt',
    content_type: 'text/plain',
    size_bytes: 3,
    version: 'a'.repeat(64),
  },
  read_grant: 'selected-grant',
  expires_at: new Date(Date.now() + 120000).toISOString(),
});
const jsonResponse = (value) =>
  new Response(JSON.stringify(value), {
    headers: { 'Content-Type': 'application/json' },
  });
async function flushFileRequest(f) {
  for (let count = 0; count < 30; count++) {
    const request = f.messages.findLast(
      (message) => message.type === 'miy.app.file-picker.request',
    );
    if (request) return request;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail('File request was not emitted');
}
async function fileFixture(
  t,
  fetcher = async (_path, init) =>
    jsonResponse(proofFor(JSON.parse(init.body).selection_id)),
) {
  t.mock.method(globalThis, 'fetch', fetcher);
  const f = fixture(fileInstall);
  f.session.permissions = ['identity:read', 'files:read-selected'];
  f.session.expires_at = new Date(Date.now() + 300000).toISOString();
  const controller = new AbortController();
  let capability;
  const connected = connectApp({
    ...f.options,
    signal: controller.signal,
    onFilePickerReady: (value) => {
      capability = value;
    },
    exchange: async () => f.session,
  });
  await f.sent;
  assert.equal(f.messages[0].file_picker_version, 1);
  f.send({ file_picker_version: 1 });
  assert.deepEqual(await connected, f.session);
  t.after(() => controller.abort());
  return {
    ...f,
    controller,
    selectFile: capability.selectFile,
    answer: (request, result, overrides = {}) =>
      f.send({
        type: 'miy.app.file-picker.result',
        file_picker_version: 1,
        selection_id: request.selection.selection_id,
        result,
        ...overrides,
      }),
  };
}

test('file capability requires an AbortSignal, current permissions and negotiated support without changing legacy sessions', async () => {
  for (const [version, permissions] of [
    [undefined, ['identity:read', 'files:read-selected']],
    [2, ['identity:read', 'files:read-selected']],
    [1, ['identity:read']],
    [1, ['files:read-selected']],
    [1, undefined],
  ]) {
    const f = fixture(fileInstall);
    const controller = new AbortController();
    let calls = 0;
    f.session.permissions = permissions;
    await assert.rejects(
      connectApp({ ...f.options, onFilePickerReady() {} }),
      /AbortSignal/,
    );
    const connected = connectApp({
      ...f.options,
      signal: controller.signal,
      onFilePickerReady() {
        calls++;
      },
      exchange: async () => f.session,
    });
    await f.sent;
    f.send({ file_picker_version: version });
    assert.deepEqual(await connected, f.session);
    assert.equal(calls, 0);
    controller.abort();
  }
});

test('file callback is not exposed before a valid session or after an aborted exchange', async () => {
  for (const result of ['valid', 'invalid', 'aborted']) {
    const f = fixture(fileInstall);
    const controller = new AbortController();
    let calls = 0;
    let complete;
    f.session.permissions = ['identity:read', 'files:read-selected'];
    const connected = connectApp({
      ...f.options,
      signal: controller.signal,
      onFilePickerReady() {
        calls++;
      },
      exchange: () =>
        new Promise((resolve) => {
          complete = resolve;
        }),
    });
    await f.sent;
    f.send({ file_picker_version: 1 });
    assert.equal(calls, 0);
    const rejected = result === 'valid' ? null : assert.rejects(connected);
    if (result === 'aborted') controller.abort();
    complete(
      result === 'invalid'
        ? { ...f.session, audience: 'https://wrong.test' }
        : f.session,
    );
    if (rejected) await rejected;
    else await connected;
    assert.equal(calls, result === 'valid' ? 1 : 0);
    controller.abort();
  }
});

test('file selection proof and read use fixed routes; postMessage never transports either bearer or file bytes', async (t) => {
  const calls = [];
  const f = await fileFixture(t, async (path, init) => {
    calls.push([path, init]);
    return path.endsWith('selection-request')
      ? jsonResponse(proofFor(JSON.parse(init.body).selection_id))
      : new Response('abc', {
          headers: {
            'Content-Type': 'application/octet-stream',
            'Content-Length': '3',
          },
        });
  });
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    schema_version: 1,
    selection_id: request.selection.selection_id,
  });
  assert.equal(calls[0][0], '/api/platform-files/selection-request');
  assert.equal(calls[0][1].headers.Authorization, `Bearer ${f.session.token}`);
  assert.equal(calls[0][1].redirect, 'error');
  assert.equal(JSON.stringify(request).includes(f.session.token), false);
  assert.deepEqual(await f.selectFile(), { status: 'busy' });
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  const selected = await pending;
  assert.equal(selected.status, 'selected');
  assert.deepEqual(selected.file, {
    fileId,
    name: 'synthetic.txt',
    contentType: 'text/plain',
    sizeBytes: 3,
    version: 'a'.repeat(64),
  });
  assert.equal(selected.readGrant, 'selected-grant');
  assert.equal(new TextDecoder().decode(await selected.read()), 'abc');
  assert.equal(calls[1][0], '/api/platform-files/content');
  assert.deepEqual(calls[1][1].headers, {
    Authorization: `Bearer ${f.session.token}`,
    'X-MIY-Selected-File': 'selected-grant',
  });
  assert.equal(calls[1][1].credentials, 'omit');
  f.controller.abort();
  await assert.rejects(selected.read(), /Selected file access unavailable/);
  assert.equal(calls.length, 2);
});

test('file results pin exact host/origin/nonce/version/selection context and reject extra fields', async (t) => {
  const f = await fileFixture(t);
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  const result = {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  };
  const response = {
    type: 'miy.app.file-picker.result',
    file_picker_version: 1,
    selection_id: request.selection.selection_id,
    result,
  };
  let completed = false;
  pending.then(() => {
    completed = true;
  });
  f.send(response, {}, 'https://platform.test');
  f.send(response, f.host, 'https://evil.test');
  f.send({ ...response, request_id: 'old' });
  f.send({ ...response, file_picker_version: 2 });
  f.send({ ...response, selection_id: fileId });
  await Promise.resolve();
  assert.equal(completed, false);
  f.answer(request, {
    status: 'selected',
    selection: { ...result.selection, storage_key: 'forbidden' },
  });
  assert.deepEqual(await pending, { status: 'unavailable' });
});

test('malformed, oversized, foreign, expired and unavailable request proofs never open a host picker', async (t) => {
  let kind = 'foreign';
  const f = await fileFixture(t, async (_path, init) => {
    const value = proofFor(JSON.parse(init.body).selection_id);
    if (kind === 'foreign') value.audience = 'https://other.test';
    if (kind === 'expired') value.expires_at = '2000-01-01T00:00:00Z';
    if (kind === 'oversized') value.selection_request = 'x'.repeat(20000);
    if (kind === 'malformed') return jsonResponse([]);
    if (kind === 'unavailable')
      return new Response('unavailable', { status: 503 });
    return jsonResponse(value);
  });
  for (kind of ['foreign', 'expired', 'oversized', 'malformed', 'unavailable'])
    assert.deepEqual(await f.selectFile(), { status: 'unavailable' });
  assert.equal(
    f.messages.filter(
      (message) => message.type === 'miy.app.file-picker.request',
    ).length,
    0,
  );
});

test('file request rate, explicit cancellation and abort are bounded without retries', async (t) => {
  const f = await fileFixture(t);
  for (let index = 0; index < 6; index++) {
    const pending = f.selectFile();
    await new Promise((resolve) => setImmediate(resolve));
    const request = await flushFileRequest(f);
    f.answer(request, { status: 'canceled' });
    assert.deepEqual(await pending, { status: 'canceled' });
  }
  assert.deepEqual(await f.selectFile(), { status: 'busy' });
  f.controller.abort();
  assert.deepEqual(await f.selectFile(), { status: 'unavailable' });
  assert.equal(getEventListeners(f.appWindow, 'message').length, 0);
});

test('aborting an outstanding file picker notifies only its exact host channel', async (t) => {
  const f = await fileFixture(t);
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  f.controller.abort();
  assert.deepEqual(await pending, { status: 'unavailable' });
  assert.deepEqual(f.messages.at(-1), {
    type: 'miy.app.file-picker.cancel',
    version: 1,
    file_picker_version: 1,
    installation_id: fileInstall,
    request_id: request.request_id,
    selection_id: request.selection.selection_id,
  });
});

test('selected content refuses oversized/truncated/encoded and redirected bodies and does not retry', async (t) => {
  let variant = 'oversized';
  let reads = 0;
  const f = await fileFixture(t, async (path, init) => {
    if (path.endsWith('selection-request'))
      return jsonResponse(proofFor(JSON.parse(init.body).selection_id));
    reads++;
    if (variant === 'oversized')
      return new Response('abc', {
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': '10485761',
        },
      });
    if (variant === 'truncated')
      return new Response('ab', {
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': '3',
        },
      });
    if (variant === 'encoded')
      return new Response('abc', {
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': '3',
          'Content-Encoding': 'gzip',
        },
      });
    const response = new Response('abc', {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Length': '3',
      },
    });
    Object.defineProperty(response, 'redirected', { value: true });
    return response;
  });
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  const selected = await pending;
  for (variant of ['oversized', 'truncated', 'encoded', 'redirected'])
    await assert.rejects(selected.read(), /Selected file access unavailable/);
  assert.equal(reads, 4);
});

test('read timeout covers an uncompleted response body and caller cancellation releases the stream', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let canceled = 0;
  let reads = 0;
  const f = await fileFixture(t, async (path, init) => {
    if (path.endsWith('selection-request'))
      return jsonResponse(proofFor(JSON.parse(init.body).selection_id));
    reads++;
    return new Response(
      new ReadableStream({
        pull() {},
        cancel() {
          canceled++;
        },
      }),
      {
        headers: {
          'Content-Type': 'application/octet-stream',
          'Content-Length': '3',
        },
      },
    );
  });
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  const selected = await pending;
  const first = selected.read();
  const rejected = assert.rejects(first, /Selected file access unavailable/);
  await new Promise((resolve) => setImmediate(resolve));
  t.mock.timers.tick(20000);
  await rejected;
  assert.equal(canceled, 1);
  const controller = new AbortController();
  const second = selected.read({ signal: controller.signal });
  const aborted = assert.rejects(second, /Selected file access unavailable/);
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  await aborted;
  assert.equal(canceled, 2);
  assert.equal(reads, 2);
});

test('proof fetch timeout and selection expiry release work without retry or a late host open', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let calls = 0;
  let complete;
  const f = await fileFixture(t, async (_path, init) => {
    calls++;
    if (calls === 1)
      return new Promise((resolve) => {
        complete = () =>
          resolve(jsonResponse(proofFor(JSON.parse(init.body).selection_id)));
      });
    return jsonResponse(proofFor(JSON.parse(init.body).selection_id));
  });
  const first = f.selectFile();
  t.mock.timers.tick(5000);
  assert.deepEqual(await first, { status: 'unavailable' });
  complete();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(
    f.messages.filter(
      (message) => message.type === 'miy.app.file-picker.request',
    ).length,
    0,
  );
  const second = f.selectFile();
  const request = await flushFileRequest(f);
  t.mock.timers.tick(60000);
  assert.deepEqual(await second, { status: 'unavailable' });
  assert.equal(f.messages.at(-1).type, 'miy.app.file-picker.cancel');
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  assert.equal(calls, 2);
});

test('selected file read remains pinned to its original connection and expires without another network call', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  let reads = 0;
  let authorization;
  const f = await fileFixture(t, async (path, init) => {
    if (path.endsWith('selection-request'))
      return jsonResponse(proofFor(JSON.parse(init.body).selection_id));
    reads++;
    authorization = init.headers.Authorization;
    return new Response('abc', {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Length': '3',
      },
    });
  });
  assert.deepEqual(await f.selectFile({ url: 'https://forbidden.test' }), {
    status: 'unavailable',
  });
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  const result = await pending;
  f.session.token = 'changed-app-owned-value';
  result.readGrant = 'changed-app-owned-value';
  result.file.sizeBytes = 500;
  assert.equal(new TextDecoder().decode(await result.read()), 'abc');
  assert.equal(authorization, `Bearer ${'s'.repeat(43)}`);
  t.mock.timers.tick(120001);
  await assert.rejects(result.read(), /Selected file access unavailable/);
  assert.equal(reads, 1);
});

test('zero-byte selected files retain the same exact-size and fixed-route contract', async (t) => {
  const f = await fileFixture(t, async (path, init) =>
    path.endsWith('selection-request')
      ? jsonResponse(proofFor(JSON.parse(init.body).selection_id))
      : new Response(null, {
          headers: {
            'Content-Type': 'application/octet-stream',
            'Content-Length': '0',
          },
        }),
  );
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  const selection = selectedFor(request.selection.selection_id);
  selection.file.size_bytes = 0;
  selection.file.name = '';
  f.answer(request, { status: 'selected', selection });
  const result = await pending;
  assert.equal(result.status, 'selected');
  assert.equal((await result.read()).byteLength, 0);
});

test('file body exceeding its selected size is canceled at the first excess chunk', async (t) => {
  let canceled = 0;
  const f = await fileFixture(t, async (path, init) =>
    path.endsWith('selection-request')
      ? jsonResponse(proofFor(JSON.parse(init.body).selection_id))
      : new Response(
          new ReadableStream({
            start(controller) {
              controller.enqueue(new Uint8Array(4));
            },
            cancel() {
              canceled++;
            },
          }),
          {
            headers: {
              'Content-Type': 'application/octet-stream',
              'Content-Length': '3',
            },
          },
        ),
  );
  const pending = f.selectFile();
  const request = await flushFileRequest(f);
  f.answer(request, {
    status: 'selected',
    selection: selectedFor(request.selection.selection_id),
  });
  const result = await pending;
  await assert.rejects(result.read(), /Selected file access unavailable/);
  assert.equal(canceled, 1);
});

for (const field of ['name', 'content_type']) {
  for (const [label, value, accepted] of [
    ['BMP255', '가'.repeat(255), true],
    ['BMP256', '가'.repeat(256), false],
    ['astral128', '📄'.repeat(128), true],
    ['astral255', '📄'.repeat(255), true],
    ['astral256', '📄'.repeat(256), false],
    ['mixed255', '가'.repeat(254) + '📄', true],
  ]) {
    test(`selected metadata ${field} uses Core code-point bounds: ${label}`, async (t) => {
      const f = await fileFixture(t);
      const pending = f.selectFile();
      const request = await flushFileRequest(f);
      const selection = selectedFor(request.selection.selection_id);
      selection.file[field] = value;
      f.answer(request, { status: 'selected', selection });
      const result = await pending;
      assert.equal(result.status, accepted ? 'selected' : 'unavailable');
      if (accepted)
        assert.equal(
          result.file[field === 'name' ? 'name' : 'contentType'],
          value,
        );
    });
  }
}
