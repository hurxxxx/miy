import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetchJson } from '@/src/platform/api/client';
import { requestDecision } from './ai-api';
import { buildCandidates } from './ai-candidates';
import { startGame } from './engine';

vi.mock('@/src/platform/api/client', () => ({ apiFetchJson: vi.fn() }));

class TestWorker {
  static instances: TestWorker[] = [];
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessageerror: (() => void) | null = null;
  postMessage = vi.fn();
  terminate = vi.fn();
  constructor() {
    TestWorker.instances.push(this);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  TestWorker.instances = [];
  vi.stubGlobal('Worker', TestWorker);
});
afterEach(() => vi.unstubAllGlobals());

describe('asynchronous Tetris observations', () => {
  it('keeps search off the UI thread and sends all visible pieces after it completes', async () => {
    const game = { ...startGame(() => 0.5), hold: 'I' as const };
    const candidates = buildCandidates(game);
    vi.mocked(apiFetchJson).mockResolvedValue({
      action: 'left',
      latency_ms: 300,
    });
    const signal = new AbortController().signal;
    const pending = requestDecision('test-token', game, signal);
    const worker = TestWorker.instances[0];
    expect(worker.postMessage).toHaveBeenCalledWith({
      ...game,
      queue: [game.queue[0]],
    });
    expect(apiFetchJson).not.toHaveBeenCalled();
    worker.onmessage!({ data: candidates });
    await expect(pending).resolves.toMatchObject({ action: 'left' });
    const [, token, init] = vi.mocked(apiFetchJson).mock.calls[0];
    expect(token).toBe('test-token');
    expect(JSON.parse(init!.body as string)).toMatchObject({
      hold: 'I',
      next: game.queue[0],
      can_hold: true,
      candidates,
    });
    expect(worker.terminate).toHaveBeenCalledOnce();
  });

  it('cancels computation without starting a model call and ignores a late worker reply', async () => {
    const controller = new AbortController();
    const pending = requestDecision(
      'test-token',
      startGame(),
      controller.signal,
    );
    const rejected = expect(pending).rejects.toMatchObject({
      name: 'AbortError',
    });
    const worker = TestWorker.instances[0];
    controller.abort();
    worker.onmessage!({ data: [] });
    await rejected;
    expect(worker.terminate).toHaveBeenCalledOnce();
    expect(apiFetchJson).not.toHaveBeenCalled();
  });

  it('sends the selected catalog model and only the opponent’s public observation', async () => {
    const game = startGame(() => 0.5);
    const opponent = { ...startGame(() => 0.2), hold: 'T' as const };
    const model = { kind: 'generation' as const, model_id: 'catalog-id' };
    vi.mocked(apiFetchJson).mockResolvedValue({ action: 'drop' });
    const pending = requestDecision(
      'test-token',
      game,
      new AbortController().signal,
      model,
      opponent,
    );
    TestWorker.instances[0].onmessage!({ data: buildCandidates(game) });
    await pending;
    const init = vi.mocked(apiFetchJson).mock.calls[0][2];
    const body = JSON.parse(init!.body as string);
    expect(body.model_choice).toEqual(model);
    expect(body.opponent).toEqual({
      board: opponent.board,
      active: opponent.active,
      next: opponent.queue[0],
      hold: 'T',
      can_hold: true,
      score: 0,
      lines: 0,
      level: 1,
    });
    expect(body.opponent).not.toHaveProperty('queue');
    expect(body.opponent).not.toHaveProperty('pieceId');
  });

  it('releases a failed worker and propagates failure to the retry loop', async () => {
    const pending = requestDecision(
      'test-token',
      startGame(),
      new AbortController().signal,
    );
    TestWorker.instances[0].onerror!();
    await expect(pending).rejects.toThrow(/AI/);
    expect(TestWorker.instances[0].terminate).toHaveBeenCalledOnce();
    expect(apiFetchJson).not.toHaveBeenCalled();
  });

  it('does not allocate workers for missing auth or an already cancelled request', async () => {
    await expect(
      requestDecision(null, startGame(), new AbortController().signal),
    ).rejects.toThrow(/AI/);
    const controller = new AbortController();
    controller.abort();
    await expect(
      requestDecision('test-token', startGame(), controller.signal),
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(TestWorker.instances).toHaveLength(0);
    expect(apiFetchJson).not.toHaveBeenCalled();
  });
});
