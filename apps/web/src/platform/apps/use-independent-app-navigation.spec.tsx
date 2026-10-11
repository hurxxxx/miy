import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { resolveIndependentNavigation } from './independent-app-navigation';
import { useIndependentAppNavigation } from './use-independent-app-navigation';
vi.mock('./independent-app-navigation', () => ({
  resolveIndependentNavigation: vi.fn(),
}));
const target = { app_id: 'planner' };
const destination = {
  target,
  path: '/apps/planner',
  identity: 'planner',
  label: 'Planner',
};
const input = {
  token: 'token',
  actorId: 'actor',
  source: {
    appId: 'source-app',
    installationId: 'source',
    generation: 1,
    origin: 'https://source.test',
    entrypoint: '/',
  },
  documentVersion: '0',
  locale: 'en-US',
};
const controllers: AbortController[] = [];
const channel = () => {
  const controller = new AbortController();
  controllers.push(controller);
  return controller;
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(resolveIndependentNavigation).mockResolvedValue(destination);
});
afterEach(() => {
  act(() => controllers.splice(0).forEach((controller) => controller.abort()));
  vi.useRealTimers();
});
function setup() {
  const navigate = vi.fn();
  return {
    navigate,
    ...renderHook(
      (props) => useIndependentAppNavigation({ ...props, navigate }),
      { initialProps: input },
    ),
  };
}
async function offer(
  run: ReturnType<typeof setup>,
  controller = channel(),
  current = () => true,
) {
  await act(async () => {
    expect(
      await run.result.current.offerNavigation(
        target,
        controller.signal,
        current,
      ),
    ).toBe('offered');
  });
  return controller;
}
it('offers without moving, then resolves current access again before an explicit click', async () => {
  const run = setup();
  await offer(run);
  expect(run.navigate).not.toHaveBeenCalled();
  expect(run.result.current.offer?.destination.label).toBe('Planner');
  expect(
    await run.result.current.offerNavigation(
      target,
      channel().signal,
      () => true,
    ),
  ).toBe('busy');
  await act(async () => {
    await run.result.current.accept();
  });
  expect(resolveIndependentNavigation).toHaveBeenCalledTimes(2);
  expect(run.navigate).toHaveBeenCalledExactlyOnceWith('/apps/planner');
  expect(run.result.current.offer).toBeNull();
});
it.each([
  'revoked',
  'different-target',
  'closed-before',
  'closed-during',
  'new-login',
  'new-document',
  'unmount',
])('never moves after %s while verifying a click', async (mode) => {
  const run = setup();
  let current = true;
  await offer(run, channel(), () => current);
  let finish!: (value: typeof destination | null) => void;
  vi.mocked(resolveIndependentNavigation).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  if (mode === 'closed-before') current = false;
  let pending!: Promise<void>;
  act(() => {
    pending = run.result.current.accept();
  });
  if (mode === 'closed-during') current = false;
  if (mode === 'new-login') run.rerender({ ...input, token: 'new-token' });
  if (mode === 'new-document') run.rerender({ ...input, documentVersion: '1' });
  if (mode === 'unmount') run.unmount();
  await act(async () => {
    finish?.(
      mode === 'revoked'
        ? null
        : mode === 'different-target'
          ? { ...destination, identity: 'new-generation' }
          : destination,
    );
    await pending;
  });
  expect(run.navigate).not.toHaveBeenCalled();
  if (mode !== 'unmount') expect(run.result.current.offer).toBeNull();
});
it.each(['token', 'source', 'document'])(
  'ignores an old %s proposal response',
  async (mode) => {
    const run = setup();
    let finish!: (value: typeof destination) => void;
    vi.mocked(resolveIndependentNavigation).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    let pending!: Promise<string>;
    act(() => {
      pending = run.result.current.offerNavigation(
        target,
        channel().signal,
        () => true,
      );
    });
    run.rerender({
      ...input,
      ...(mode === 'token'
        ? { token: 'new-token' }
        : mode === 'source'
          ? { source: { ...input.source, generation: 2 } }
          : { documentVersion: '1' }),
    });
    await act(async () => {
      finish(destination);
      expect(await pending).toBe('unavailable');
    });
    expect(run.result.current.offer).toBeNull();
    expect(run.navigate).not.toHaveBeenCalled();
    await offer(run);
    expect(run.result.current.offer).not.toBeNull();
  },
);
it('clears on channel renewal, dismissal, expiry and click timeout even if fetch ignores abort', async () => {
  vi.useFakeTimers();
  const run = setup();
  const controller = await offer(run);
  act(() => controller.abort());
  expect(run.result.current.offer).toBeNull();
  await offer(run);
  act(() => run.result.current.dismiss());
  expect(run.result.current.offer).toBeNull();
  await offer(run);
  act(() => vi.advanceTimersByTime(30000));
  expect(run.result.current.offer).toBeNull();
  await offer(run);
  let finish!: (value: typeof destination) => void;
  vi.mocked(resolveIndependentNavigation).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  let pending!: Promise<void>;
  act(() => {
    pending = run.result.current.accept();
  });
  expect(run.result.current.offer?.checking).toBe(true);
  act(() => vi.advanceTimersByTime(8000));
  expect(run.result.current.offer).toBeNull();
  await act(async () => {
    finish(destination);
    await pending;
  });
  expect(run.navigate).not.toHaveBeenCalled();
});
