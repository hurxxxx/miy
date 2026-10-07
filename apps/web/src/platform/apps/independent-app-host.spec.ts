import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  independentAppOrigin,
  listenForIndependentApp,
  type IndependentUIContext,
  checkedIndependentFileMetadata,
  checkedIndependentSelectedFile,
  type IndependentFileSelectionRequest,
  type IndependentFileSelectionResult,
} from './independent-app-host';

const origin = 'https://app.example.test';
const message = {
  type: 'miy.app.ready',
  version: 1,
  installation_id: 'install-1',
  request_id: '12345678-1234-4321-8765-123456789abc',
  code_challenge: 'a'.repeat(43),
};
const launch = () => ({
  code: 'c'.repeat(43),
  app_origin: origin,
  expires_at: new Date(Date.now() + 60000).toISOString(),
});
const controllers: AbortController[] = [];
afterEach(() => {
  controllers.splice(0).forEach((controller) => controller.abort());
  vi.useRealTimers();
});

function setup(
  issue = vi.fn().mockImplementation(() => Promise.resolve(launch())),
  getUIContext?: () => IndependentUIContext,
  offerNavigation?: Parameters<
    typeof listenForIndependentApp
  >[0]['offerNavigation'],
  selectFile?: Parameters<typeof listenForIndependentApp>[0]['selectFile'],
  installationId = 'install-1',
) {
  const controller = new AbortController();
  controllers.push(controller);
  const frame = { postMessage: vi.fn() } as unknown as Window;
  const onConnected = vi.fn();
  const onFailure = vi.fn();
  const dispose = listenForIndependentApp({
    frame,
    origin,
    installationId,
    signal: controller.signal,
    issueLaunch: issue,
    onConnected,
    onFailure,
    getUIContext,
    offerNavigation,
    selectFile,
  });
  const send = (
    data: unknown = message,
    source: Window = frame,
    eventOrigin = origin,
  ) => {
    window.dispatchEvent(
      new MessageEvent('message', { data, source, origin: eventOrigin }),
    );
  };
  return { controller, frame, issue, send, onConnected, onFailure, dispose };
}

describe('independent app host trust boundary', () => {
  it('negotiates opt-in UI context and updates without another launch', async () => {
    let value: IndependentUIContext = { theme: 'light', locale: 'ko-KR' };
    const run = setup(undefined, () => value);
    run.send({ ...message, ui_context_version: 1 });
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: 'miy.app.launch',
        ui_context: {
          version: 1,
          sequence: 0,
          theme: 'light',
          locale: 'ko-KR',
        },
      }),
      origin,
    );
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenCalledTimes(1);
    value = { theme: 'dark', locale: 'en-US' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      {
        type: 'miy.app.context',
        version: 1,
        installation_id: message.installation_id,
        request_id: message.request_id,
        ui_context: { version: 1, sequence: 1, theme: 'dark', locale: 'en-US' },
      },
      origin,
    );
    value = { theme: 'light', locale: 'en-US' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        ui_context: {
          version: 1,
          sequence: 2,
          theme: 'light',
          locale: 'en-US',
        },
      }),
      origin,
    );
    expect(run.issue).toHaveBeenCalledOnce();
    run.dispose();
    value = { theme: 'dark', locale: 'ko-KR' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenCalledTimes(3);
  });

  it.each([undefined, 2])(
    'keeps identity-only callers unchanged for context capability %s',
    async (version) => {
      let value: IndependentUIContext = { theme: 'light', locale: 'ko-KR' };
      const run = setup(undefined, () => value);
      run.send({ ...message, ui_context_version: version });
      await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
      expect(
        vi.mocked(run.frame.postMessage).mock.calls[0][0],
      ).not.toHaveProperty('ui_context');
      value = { theme: 'dark', locale: 'en-US' };
      run.dispose.updateUIContext();
      expect(run.frame.postMessage).toHaveBeenCalledTimes(1);
    },
  );

  it('snapshots current UI state after a slow launch and rebinds only to a new nonce', async () => {
    let value: IndependentUIContext = { theme: 'light', locale: 'ko-KR' };
    let resolve!: (value: ReturnType<typeof launch>) => void;
    const issue = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      )
      .mockImplementation(() => Promise.resolve(launch()));
    const run = setup(issue, () => value);
    run.send({ ...message, ui_context_version: 1 });
    value = { theme: 'dark', locale: 'en-US' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).not.toHaveBeenCalled();
    resolve(launch());
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        ui_context: { version: 1, sequence: 0, ...value },
      }),
      origin,
    );
    const requestId = '22345678-1234-4321-8765-123456789abc';
    run.send({ ...message, ui_context_version: 1, request_id: requestId });
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledTimes(2));
    value = { theme: 'light', locale: 'en-US' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: 'miy.app.context',
        request_id: requestId,
        ui_context: { version: 1, sequence: 1, ...value },
      }),
      origin,
    );
    Object.defineProperty(run.frame, 'closed', { value: true });
    value = { theme: 'dark', locale: 'en-US' };
    run.dispose.updateUIContext();
    expect(run.frame.postMessage).toHaveBeenCalledTimes(3);
  });
  it('sends only one short-lived launch code to the exact matching frame and origin', async () => {
    const run = setup();
    run.send();
    run.send();
    await vi.waitFor(() =>
      expect(run.frame.postMessage).toHaveBeenCalledTimes(1),
    );
    expect(run.issue).toHaveBeenCalledExactlyOnceWith(
      message.code_challenge,
      expect.any(AbortSignal),
    );
    expect(run.frame.postMessage).toHaveBeenCalledWith(
      {
        type: 'miy.app.launch',
        version: 1,
        installation_id: 'install-1',
        request_id: message.request_id,
        ...{ code: launch().code, expires_at: expect.any(String) },
      },
      origin,
    );
    expect(run.onConnected).toHaveBeenCalledOnce();
  });

  it('renews after five minutes with a new nonce without reloading the document', async () => {
    vi.useFakeTimers();
    const run = setup();
    run.send();
    await vi.advanceTimersByTimeAsync(0);
    expect(run.onConnected).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5 * 60000);
    run.send({
      ...message,
      request_id: '22345678-1234-4321-8765-123456789abc',
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(run.issue).toHaveBeenCalledTimes(2);
    expect(run.onConnected).toHaveBeenCalledTimes(2);
  });

  it('allows a fresh nonce after exchange failure while deduplicating the prior nonce', async () => {
    const run = setup();
    run.send();
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    // Exchange occurs in the app. Its failed exchange starts a new handshake.
    run.send();
    run.send({
      ...message,
      request_id: '22345678-1234-4321-8765-123456789abc',
    });
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledTimes(2));
    run.send();
    expect(run.issue).toHaveBeenCalledTimes(2);
  });

  it('serializes different nonces and permits retry after a failed launch', async () => {
    let reject!: (error: Error) => void;
    const issue = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((_, fail) => {
            reject = fail;
          }),
      )
      .mockImplementation(() => Promise.resolve(launch()));
    const run = setup(issue);
    const next = {
      ...message,
      request_id: '22345678-1234-4321-8765-123456789abc',
    };
    run.send();
    run.send(next);
    expect(issue).toHaveBeenCalledOnce();
    reject(new Error('Synthetic launch failure'));
    await vi.waitFor(() => expect(run.onFailure).toHaveBeenCalledOnce());
    run.send();
    expect(issue).toHaveBeenCalledOnce();
    run.send(next);
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    expect(issue).toHaveBeenCalledTimes(2);
  });

  it('bounds unique nonce attempts and recovers after the rate window', async () => {
    vi.useFakeTimers();
    const run = setup();
    for (let index = 0; index < 1000; index += 1) {
      run.send({
        ...message,
        request_id: `${String(index).padStart(8, '0')}-1234-4321-8765-123456789abc`,
      });
      await vi.advanceTimersByTimeAsync(0);
    }
    expect(run.issue).toHaveBeenCalledTimes(6);
    expect(run.onFailure).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(60000);
    run.send();
    await vi.advanceTimersByTimeAsync(0);
    expect(run.issue).toHaveBeenCalledTimes(7);
  });

  it('expires a hung renewal and rejects its late result after a newer request', async () => {
    vi.useFakeTimers();
    let resolve!: (value: ReturnType<typeof launch>) => void;
    const issue = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      )
      .mockImplementation(() => Promise.resolve(launch()));
    const run = setup(issue);
    run.send();
    const firstSignal = issue.mock.calls[0][1] as AbortSignal;
    await vi.advanceTimersByTimeAsync(10000);
    expect(firstSignal.aborted).toBe(true);
    expect(run.onFailure).toHaveBeenCalledOnce();
    run.send({
      ...message,
      request_id: '22345678-1234-4321-8765-123456789abc',
    });
    await vi.advanceTimersByTimeAsync(0);
    resolve(launch());
    await vi.advanceTimersByTimeAsync(0);
    expect(run.frame.postMessage).toHaveBeenCalledTimes(1);
    expect(run.onConnected).toHaveBeenCalledOnce();
  });

  it('ignores forged origin, sibling windows, wrong installation, protocol and malformed challenges', async () => {
    const run = setup();
    run.send(message, run.frame, 'https://other.example.test');
    run.send(message, window);
    run.send({ ...message, installation_id: 'another-install' });
    run.send({ ...message, version: 2 });
    run.send({ ...message, request_id: 'not-a-request-id' });
    run.send({ ...message, code_challenge: 'short' });
    await Promise.resolve();
    expect(run.issue).not.toHaveBeenCalled();
    expect(run.frame.postMessage).not.toHaveBeenCalled();
  });

  it('does not deliver an in-flight code after frame navigation or user/session change', async () => {
    let resolve!: (value: ReturnType<typeof launch>) => void;
    const run = setup(
      vi.fn().mockImplementation(
        () =>
          new Promise((done) => {
            resolve = done;
          }),
      ),
    );
    run.send();
    run.controller.abort();
    resolve(launch());
    await Promise.resolve();
    expect(run.frame.postMessage).not.toHaveBeenCalled();
    expect(run.onConnected).not.toHaveBeenCalled();
    run.send();
    expect(run.issue).toHaveBeenCalledOnce();
  });

  it.each([
    { ...launch(), app_origin: 'https://wrong.example.test' },
    { ...launch(), expires_at: '2000-01-01T00:00:00Z' },
    { ...launch(), code: 'bad' },
  ])('rejects mismatched or expired server evidence', async (value) => {
    const run = setup(vi.fn().mockResolvedValue(value));
    run.send();
    await vi.waitFor(() => expect(run.onFailure).toHaveBeenCalledOnce());
    expect(run.frame.postMessage).not.toHaveBeenCalled();
  });

  it('rejects same-origin, credentials, paths and insecure nonlocal origins', () => {
    for (const value of [
      origin,
      'https://user@app.example.test',
      'https://app.example.test/path',
      'http://app.example.test',
      'javascript:alert(1)',
    ]) {
      expect(independentAppOrigin(value, origin)).toBeNull();
    }
    expect(independentAppOrigin('http://127.0.0.1:8020', origin)).toBe(
      'http://127.0.0.1:8020',
    );
  });
});

const navMessage = (id = '22222222-2222-4222-8222-222222222222') => ({
  type: 'miy.app.navigation.request',
  version: 1,
  navigation_version: 1,
  installation_id: message.installation_id,
  request_id: message.request_id,
  navigation_id: id,
  target: { app_id: 'planner' },
});

it.each([undefined, 2])(
  'keeps old navigation capability %s callers on the original identity protocol',
  async (version) => {
    const offer = vi.fn().mockResolvedValue('offered');
    const run = setup(undefined, undefined, offer);
    run.send({ ...message, navigation_version: version });
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    expect(
      vi.mocked(run.frame.postMessage).mock.calls[0][0],
    ).not.toHaveProperty('navigation_version');
    run.send(navMessage());
    await Promise.resolve();
    expect(offer).not.toHaveBeenCalled();
  },
);

it('pins navigation to current frame/origin/nonce and never carries credentials or an arbitrary route', async () => {
  const offer = vi.fn().mockResolvedValue('offered');
  const run = setup(undefined, undefined, offer);
  run.send({ ...message, navigation_version: 1 });
  await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
  expect(
    vi.mocked(run.frame.postMessage).mock.calls[0][0].navigation_version,
  ).toBe(1);
  run.send(navMessage(), window);
  run.send(navMessage(), run.frame, 'https://wrong.test');
  run.send({ ...navMessage(), request_id: crypto.randomUUID() });
  run.send({ ...navMessage(), navigation_version: 2 });
  run.send({
    ...navMessage(),
    target: { app_id: 'planner', path: 'https://evil.test' },
  });
  run.send({ ...navMessage(), installation_id: 'another' });
  expect(offer).not.toHaveBeenCalled();
  run.send(navMessage());
  await vi.waitFor(() => expect(offer).toHaveBeenCalledOnce());
  expect(offer.mock.calls[0][0]).toEqual({ app_id: 'planner' });
  expect(offer.mock.calls[0][2]()).toBe(true);
  await vi.waitFor(() =>
    expect(run.frame.postMessage).toHaveBeenCalledTimes(2),
  );
  const expected = {
    version: 1,
    navigation_version: 1,
    installation_id: message.installation_id,
    request_id: message.request_id,
    navigation_id: navMessage().navigation_id,
  };
  expect(run.frame.postMessage).toHaveBeenLastCalledWith(
    { ...expected, type: 'miy.app.navigation.result', status: 'offered' },
    origin,
  );
});

it('bounds replay/floods and closes visible offer authority on nonce renewal, popup close and expiry', async () => {
  vi.useFakeTimers();
  const offer = vi.fn().mockResolvedValue('offered');
  const run = setup(undefined, undefined, offer);
  run.send({ ...message, navigation_version: 1 });
  await vi.advanceTimersByTimeAsync(0);
  for (let count = 0; count < 8; count++) {
    run.send(navMessage(crypto.randomUUID()));
    await vi.advanceTimersByTimeAsync(0);
  }
  expect(offer).toHaveBeenCalledTimes(6);
  const [, signal, isCurrent] = offer.mock.calls[0];
  run.send({
    ...message,
    request_id: crypto.randomUUID(),
    navigation_version: 1,
  });
  expect(signal.aborted).toBe(true);
  expect(isCurrent()).toBe(false);
  await vi.advanceTimersByTimeAsync(0);
  Object.defineProperty(run.frame, 'closed', {
    configurable: true,
    value: true,
  });
  await vi.advanceTimersByTimeAsync(1000);
  run.send(navMessage());
  expect(offer).toHaveBeenCalledTimes(6);
});

it('aborts a never-resolving navigation request at its deadline without another issueLaunch', async () => {
  vi.useFakeTimers();
  const offer = vi.fn().mockImplementation(() => new Promise(() => undefined));
  const run = setup(undefined, undefined, offer);
  run.send({ ...message, navigation_version: 1 });
  await vi.advanceTimersByTimeAsync(0);
  run.send(navMessage());
  expect(offer).toHaveBeenCalledOnce();
  const [, signal, isCurrent] = offer.mock.calls[0];
  await vi.advanceTimersByTimeAsync(9000);
  expect(signal.aborted).toBe(true);
  expect(isCurrent()).toBe(false);
  expect(run.issue).toHaveBeenCalledOnce();
  expect(run.frame.postMessage).toHaveBeenCalledTimes(1);
});

it.each(['popup-close', 'expiry'])(
  'invalidates active %s synchronously before the cleanup timer runs',
  async (reason) => {
    vi.useFakeTimers();
    const offer = vi.fn().mockResolvedValue('offered');
    const run = setup(undefined, undefined, offer);
    run.send({ ...message, navigation_version: 1 });
    await vi.advanceTimersByTimeAsync(0);
    run.send(navMessage());
    await vi.advanceTimersByTimeAsync(0);
    const [, signal, isCurrent] = offer.mock.calls[0];
    expect(signal.aborted).toBe(false);
    expect(isCurrent()).toBe(true);
    if (reason === 'popup-close')
      Object.defineProperty(run.frame, 'closed', { value: true });
    else vi.setSystemTime(Date.now() + 300001);
    expect(signal.aborted).toBe(false);
    expect(isCurrent()).toBe(false);
  },
);

const fileInstallation = '82345678-1234-4321-8765-123456789abc';
const selectionId = '92345678-1234-4321-8765-123456789abc';
const selectedFileId = 'a2345678-1234-4321-8765-123456789abc';
const fileReady = {
  ...message,
  installation_id: fileInstallation,
  file_picker_version: 1,
};
const fileRequest = (id = selectionId): IndependentFileSelectionRequest => ({
  schema_version: 1,
  installation_id: fileInstallation,
  audience: origin,
  selection_id: id,
  selection_request: 'request-proof',
  expires_at: new Date(Date.now() + 60000).toISOString(),
  max_bytes: 10485760,
});
const fileMessage = (request = fileRequest()) => ({
  type: 'miy.app.file-picker.request',
  version: 1,
  file_picker_version: 1,
  installation_id: fileInstallation,
  request_id: message.request_id,
  selection: request,
});
const fileMetadata = () => ({
  file_id: selectedFileId,
  name: 'Synthetic.txt',
  content_type: 'text/plain',
  size_bytes: 3,
  version: 'a'.repeat(64),
});
const fileSelected = (
  request = fileRequest(),
): IndependentFileSelectionResult => ({
  status: 'selected',
  selection: {
    schema_version: 1,
    installation_id: fileInstallation,
    audience: origin,
    selection_id: request.selection_id,
    file: fileMetadata(),
    read_grant: 'read-grant',
    expires_at: new Date(Date.now() + 120000).toISOString(),
  },
});
async function fileHost(
  selectFile: NonNullable<
    Parameters<typeof listenForIndependentApp>[0]['selectFile']
  >,
) {
  const run = setup(
    undefined,
    undefined,
    undefined,
    selectFile,
    fileInstallation,
  );
  run.send(fileReady);
  await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
  return run;
}

describe('optional selected-file protocol', () => {
  it('keeps old callers unchanged and waits for exact opt-in before accepting proof', async () => {
    const select = vi.fn().mockResolvedValue({ status: 'canceled' });
    const run = setup(
      undefined,
      undefined,
      undefined,
      select,
      fileInstallation,
    );
    run.send({ ...fileReady, file_picker_version: 2 });
    await vi.waitFor(() => expect(run.onConnected).toHaveBeenCalledOnce());
    expect(
      vi.mocked(run.frame.postMessage).mock.calls[0][0],
    ).not.toHaveProperty('file_picker_version');
    run.send(fileMessage());
    expect(select).not.toHaveBeenCalled();
  });
  it('validates exact source/window/context and sends only a bounded current selected result', async () => {
    const request = fileRequest();
    const selected = fileSelected(request);
    const select = vi.fn().mockResolvedValue(selected);
    const run = await fileHost(select);
    expect(vi.mocked(run.frame.postMessage).mock.calls[0][0]).toHaveProperty(
      'file_picker_version',
      1,
    );
    run.send(fileMessage(request), {} as Window);
    run.send(fileMessage(request), run.frame, 'https://other.test');
    run.send({ ...fileMessage(request), request_id: 'old' });
    run.send({ ...fileMessage(request), file_picker_version: 2 });
    run.send(fileMessage({ ...request, audience: 'https://other.test' }));
    run.send(fileMessage({ ...request, selection_request: 'x'.repeat(4097) }));
    expect(select).not.toHaveBeenCalled();
    run.send(fileMessage(request));
    await vi.waitFor(() => expect(select).toHaveBeenCalledOnce());
    expect(select.mock.calls[0][0]).toEqual(request);
    await vi.waitFor(() =>
      expect(run.frame.postMessage).toHaveBeenLastCalledWith(
        {
          type: 'miy.app.file-picker.result',
          version: 1,
          file_picker_version: 1,
          installation_id: fileInstallation,
          request_id: message.request_id,
          selection_id: request.selection_id,
          result: selected,
        },
        origin,
      ),
    );
    run.send(fileMessage(request));
    expect(select).toHaveBeenCalledOnce();
  });
  it('rejects malformed or foreign selected results with fixed unavailable status', async () => {
    const selected = fileSelected();
    if (selected.status !== 'selected') throw new Error('fixture');
    const run = await fileHost(
      vi.fn().mockResolvedValue({
        ...selected,
        selection: { ...selected.selection, storage_key: 'forbidden' },
      }),
    );
    run.send(fileMessage());
    await vi.waitFor(() =>
      expect(run.frame.postMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({ result: { status: 'unavailable' } }),
        origin,
      ),
    );
    expect(
      checkedIndependentFileMetadata({ ...fileMetadata(), size_bytes: true }),
    ).toBeNull();
    expect(
      checkedIndependentFileMetadata({
        ...fileMetadata(),
        version: 'not-a-version',
      }),
    ).toBeNull();
    expect(
      checkedIndependentSelectedFile(
        { ...selected.selection, selection_id: selectedFileId },
        fileRequest(),
      ),
    ).toBeNull();
  });
  for (const field of ['name', 'content_type']) {
    it.each([
      ['BMP255', '가'.repeat(255), true],
      ['BMP256', '가'.repeat(256), false],
      ['astral128', '📄'.repeat(128), true],
      ['astral255', '📄'.repeat(255), true],
      ['astral256', '📄'.repeat(256), false],
      ['mixed255', '가'.repeat(254) + '📄', true],
    ])(
      `uses Core code-point bounds for ${field}: %s`,
      (_label, value, accepted) => {
        const metadata = { ...fileMetadata(), [field]: value };
        expect(checkedIndependentFileMetadata(metadata)).toEqual(
          accepted ? metadata : null,
        );
      },
    );
  }
  it('keeps at most one pending picker and a six-request replay window', async () => {
    let done!: (result: IndependentFileSelectionResult) => void;
    const select = vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          done = resolve;
        }),
    );
    const run = await fileHost(select);
    run.send(fileMessage());
    expect(select).toHaveBeenCalledOnce();
    for (let index = 1; index <= 7; index++)
      run.send(
        fileMessage(
          fileRequest(
            `92345678-1234-4321-8765-${index.toString().padStart(12, '0')}`,
          ),
        ),
      );
    expect(select).toHaveBeenCalledOnce();
    expect(
      vi
        .mocked(run.frame.postMessage)
        .mock.calls.filter(
          ([data]) => data.type === 'miy.app.file-picker.result',
        ),
    ).toHaveLength(5);
    done({ status: 'canceled' });
    await vi.waitFor(() =>
      expect(run.frame.postMessage).toHaveBeenLastCalledWith(
        expect.objectContaining({
          selection_id: selectionId,
          result: { status: 'canceled' },
        }),
        origin,
      ),
    );
  });
  it.each(['new-nonce', 'abort', 'popup-close', 'expiry', 'cancel'] as const)(
    'invalidates pending proof at %s and suppresses its late response',
    async (change) => {
      vi.useFakeTimers();
      let done!: (result: IndependentFileSelectionResult) => void;
      const select = vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            done = resolve;
          }),
      );
      const run = setup(
        undefined,
        undefined,
        undefined,
        select,
        fileInstallation,
      );
      run.send(fileReady);
      await vi.advanceTimersByTimeAsync(0);
      run.send(fileMessage());
      const [, signal, isCurrent] = select.mock.calls[0];
      expect(isCurrent()).toBe(true);
      if (change === 'new-nonce')
        run.send({ ...fileReady, request_id: selectedFileId });
      else if (change === 'abort') run.controller.abort();
      else if (change === 'popup-close')
        Object.defineProperty(run.frame, 'closed', { value: true });
      else if (change === 'expiry') vi.setSystemTime(Date.now() + 60001);
      else
        run.send({
          type: 'miy.app.file-picker.cancel',
          version: 1,
          file_picker_version: 1,
          installation_id: fileInstallation,
          request_id: message.request_id,
          selection_id: selectionId,
        });
      expect(isCurrent()).toBe(false);
      if (change === 'popup-close' || change === 'expiry')
        expect(signal.aborted).toBe(false);
      done(fileSelected());
      await vi.advanceTimersByTimeAsync(0);
      expect(
        vi
          .mocked(run.frame.postMessage)
          .mock.calls.filter(
            ([data]) => data.type === 'miy.app.file-picker.result',
          ),
      ).toHaveLength(0);
    },
  );
  it('a timed-out picker releases only that request so a new explicit request can proceed', async () => {
    vi.useFakeTimers();
    const select = vi
      .fn()
      .mockImplementationOnce(() => new Promise(() => undefined))
      .mockResolvedValue({ status: 'canceled' });
    const run = setup(
      undefined,
      undefined,
      undefined,
      select,
      fileInstallation,
    );
    run.send(fileReady);
    await vi.advanceTimersByTimeAsync(0);
    run.send(fileMessage());
    await vi.advanceTimersByTimeAsync(60001);
    expect(select.mock.calls[0][1].aborted).toBe(true);
    run.send(fileMessage(fileRequest(selectedFileId)));
    await vi.advanceTimersByTimeAsync(0);
    expect(select).toHaveBeenCalledTimes(2);
    expect(run.frame.postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        selection_id: selectedFileId,
        result: { status: 'canceled' },
      }),
      origin,
    );
  });
});
