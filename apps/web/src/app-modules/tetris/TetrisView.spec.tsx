import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode, type ReactElement } from 'react';
import { i18n } from '@/src/platform/i18n';
import { TetrisView } from './TetrisView';
import { listModels, requestDecision, type ModelOption } from './ai-api';
import { ApiRequestError } from '@/src/platform/api/client';
vi.mock('@/src/platform/auth/auth-provider', () => ({
  useAuth: () => ({ token: 'test-token' }),
}));
const feedbackError = vi.hoisted(() => vi.fn());
const feedback = { error: feedbackError };
vi.mock('@open-work-hub/ui', async (original) => ({
  ...(await original<typeof import('@open-work-hub/ui')>()),
  useFeedback: () => feedback,
}));
vi.mock('./ai-api', () => ({
  listModels: vi.fn().mockResolvedValue({ models: [] }),
  requestDecision: vi.fn(),
}));
async function renderView(ui: ReactElement) {
  return act(async () => render(ui));
}
async function renderSolo(ui: ReactElement) {
  const view = await renderView(ui);
  fireEvent.change(
    screen.getByRole('combobox', { name: /^(Player 2|플레이어 2)$/ }),
    {
      target: { value: 'none' },
    },
  );
  fireEvent.change(
    screen.getByRole('combobox', { name: /^(Player 1|플레이어 1)$/ }),
    {
      target: { value: 'human' },
    },
  );
  return view;
}
const board = () =>
  within(screen.getByRole('region', { name: 'Player 1' })).getByRole('region', {
    name: 'Game board',
  });
const cells = () => board().querySelector('[aria-hidden]')!.innerHTML;
function start() {
  fireEvent.click(screen.getByRole('button', { name: 'Start game' }));
}
beforeEach(async () => {
  await i18n.changeLanguage('en-US');
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.mocked(listModels).mockResolvedValue({ models: [] });
  vi.mocked(requestDecision).mockReset();
});
describe('tetris controls and lifecycle', async () => {
  it('loads each AI default by kind and preserves explicit choices on catalog refresh', async () => {
    const models: ModelOption[] = [
      {
        kind: 'generation',
        model_id: 'alternative',
        name: 'Alternative',
        model_key: 'test/alternative',
        provider: 'test',
        is_default: false,
      },
      {
        kind: 'generation',
        model_id: 'chat',
        name: 'Chat default',
        model_key: 'test/chat',
        provider: 'test',
        is_default: true,
      },
      {
        kind: 'decision',
        model_id: 'judge',
        name: 'Decision default',
        model_key: 'test/judge',
        provider: 'test',
        is_default: true,
      },
    ];
    let loaded!: (value: { models: ModelOption[] }) => void;
    vi.mocked(listModels).mockReturnValueOnce(
      new Promise((resolve) => {
        loaded = resolve;
      }),
    );
    vi.mocked(requestDecision).mockImplementation(() => new Promise(() => {}));
    await renderView(<TetrisView />);
    for (const player of [1, 2])
      expect(
        (
          screen.getByRole('combobox', {
            name: `Player ${player}`,
          }) as HTMLSelectElement
        ).value,
      ).toBe('ai');
    expect(
      (screen.getByRole('button', { name: 'Start game' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await act(async () => loaded({ models }));
    const modelPicker = (id: number) =>
      screen.getByRole('combobox', {
        name: `AI model for player ${id}`,
      }) as HTMLSelectElement;
    expect(modelPicker(1).value).toBe('decision:judge');
    expect(modelPicker(2).value).toBe('generation:chat');
    expect(requestDecision).not.toHaveBeenCalled();
    start();
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(
      vi.mocked(requestDecision).mock.calls.map((call) => call[3]),
    ).toEqual([
      { kind: 'decision', model_id: 'judge' },
      { kind: 'generation', model_id: 'chat' },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Pause game' }));
    fireEvent.change(modelPicker(1), {
      target: { value: 'generation:alternative' },
    });
    vi.mocked(listModels).mockResolvedValue({
      models: models.map((model) => ({
        ...model,
        is_default: model.model_id === 'judge',
      })),
    });
    await act(async () =>
      fireEvent.click(
        screen.getAllByRole('button', { name: 'Refresh models' })[0],
      ),
    );
    expect(modelPicker(1).value).toBe('generation:alternative');
    expect(modelPicker(2).value).toBe('generation:chat');
  });

  it('requires an explicit choice when a model kind has no configured default', async () => {
    vi.mocked(listModels).mockResolvedValue({
      models: [
        {
          kind: 'generation',
          model_id: 'alternative',
          name: 'Alternative',
          model_key: 'test/alternative',
          provider: 'test',
          is_default: false,
        },
      ],
    });
    await renderView(<TetrisView />);
    const startButton = screen.getByRole('button', {
      name: 'Start game',
    }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(true);
    for (const player of [1, 2]) {
      const picker = screen.getByRole('combobox', {
        name: `AI model for player ${player}`,
      }) as HTMLSelectElement;
      expect(picker.value).toBe('');
      fireEvent.change(picker, { target: { value: 'generation:alternative' } });
    }
    expect(startButton.disabled).toBe(false);
    expect(requestDecision).not.toHaveBeenCalled();
  });

  it.each([
    [429, 'tetris.ai_rate_limited', 'Model provider request limit reached'],
    [502, 'tetris.ai_output_limit', 'Model output limit reached'],
    [504, 'tetris.ai_timeout', 'Model response timed out'],
  ] as const)(
    'distinguishes failure %s from no response and clears it on success',
    async (status, code, label) => {
      vi.mocked(listModels).mockResolvedValue({
        models: [
          {
            model_id: 'test',
            name: 'Test model',
            model_key: 'test/model',
            kind: 'generation',
            provider: 'test',
            is_default: true,
          },
        ],
      });
      vi.mocked(requestDecision).mockRejectedValueOnce(
        new ApiRequestError(status, 'private', { code }),
      );
      vi.mocked(requestDecision).mockResolvedValue({
        action: 'wait',
        placement: null,
        model: 'test/model',
        kind: 'generation',
        provider: 'test',
        latency_ms: 10,
      });
      await renderSolo(<TetrisView />);
      fireEvent.change(screen.getByRole('combobox', { name: 'Player 1' }), {
        target: { value: 'ai' },
      });
      fireEvent.change(
        screen.getByRole('combobox', { name: 'AI model for player 1' }),
        {
          target: { value: 'generation:test' },
        },
      );
      start();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText(label)).toBeTruthy();
      expect(screen.getByText('No successful responses yet')).toBeTruthy();
      expect(screen.queryByText('No responses yet')).toBeNull();
      expect(screen.queryByText('private')).toBeNull();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
      expect(screen.queryByText(label)).toBeNull();
      expect(screen.queryByText('No successful responses yet')).toBeNull();
    },
  );
  it('offers screen controls with the same movement, hold and pause rules', async () => {
    await renderSolo(<TetrisView />);
    const move = screen.getByRole('button', {
      name: 'Move left',
    }) as HTMLButtonElement;
    const hold = screen.getByRole('button', {
      name: 'Hold block',
    }) as HTMLButtonElement;
    expect(move.disabled).toBe(true);
    start();
    const initial = cells();
    fireEvent.click(move);
    expect(cells()).not.toBe(initial);
    fireEvent.click(screen.getByRole('button', { name: 'Soft drop' }));
    expect(screen.getByTestId('tetris-score').textContent).toBe('1');
    fireEvent.click(hold);
    expect(hold.disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Drop instantly' }));
    expect(hold.disabled).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Pause game' }));
    expect(move.disabled).toBe(true);
    const paused = cells();
    fireEvent.click(move);
    expect(cells()).toBe(paused);
  });
  it('gives a restarted game a full gravity interval', async () => {
    await renderSolo(<TetrisView />);
    start();
    act(() => {
      vi.advanceTimersByTime(999);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Restart game' }));
    const restarted = cells();
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(cells()).toBe(restarted);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(cells()).not.toBe(restarted);
  });
  it('starts with focus and runs a single timer even in StrictMode', async () => {
    const view = await renderSolo(
      <StrictMode>
        <TetrisView />
      </StrictMode>,
    );
    expect(vi.getTimerCount()).toBe(0);
    const secondBoard = within(
      screen.getByRole('region', { name: 'Player 2' }),
    ).getByRole('region', { name: 'Game board' });
    const inactive = secondBoard.innerHTML;
    expect(secondBoard.getAttribute('aria-disabled')).toBe('true');
    start();
    expect(document.activeElement).toBe(board());
    expect(vi.getTimerCount()).toBe(1);
    const initial = cells();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(cells()).not.toBe(initial);
    expect(secondBoard.innerHTML).toBe(inactive);
    fireEvent.keyDown(secondBoard, { code: 'KeyP' });
    expect(screen.getByRole('status').textContent).toBe('Playing');
    fireEvent.keyDown(board(), { code: 'KeyP' });
    const paused = cells();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    expect(cells()).toBe(paused);
    expect(vi.getTimerCount()).toBe(0);
    fireEvent.click(screen.getByRole('button', { name: 'Resume game' }));
    expect(document.activeElement).toBe(board());
    expect(vi.getTimerCount()).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: 'Restart game' }));
    expect(vi.getTimerCount()).toBe(1);
    expect(screen.getByTestId('tetris-score').textContent).toBe('0');
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
  it('keeps playing when the window, tab or game loses focus without intercepting outside keys', async () => {
    await renderSolo(
      <>
        <TetrisView />
        <input aria-label="Outside input" />
      </>,
    );
    start();
    const initial = cells();
    fireEvent(window, new Event('blur'));
    expect(screen.getByRole('status').textContent).toBe('Playing');
    fireEvent(window, new Event('focus'));
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
    fireEvent(document, new Event('visibilitychange'));
    expect(screen.getByRole('status').textContent).toBe('Playing');
    hidden.mockRestore();
    act(() => {
      screen.getByRole('textbox').focus();
    });
    expect(screen.getByRole('status').textContent).toBe('Playing');
    const event = new KeyboardEvent('keydown', {
      code: 'Space',
      bubbles: true,
      cancelable: true,
    });
    fireEvent(screen.getByRole('textbox'), event);
    expect(event.defaultPrevented).toBe(false);
    act(() => vi.advanceTimersByTime(1000));
    expect(cells()).not.toBe(initial);
  });
  it('consumes game keys only at the board and suppresses repeat for one-shot actions', async () => {
    await renderSolo(<TetrisView />);
    start();
    const initial = cells();
    fireEvent.keyDown(board(), { code: 'Space', repeat: true });
    fireEvent.keyDown(board(), { code: 'KeyC', repeat: true });
    fireEvent.keyDown(board(), { code: 'ArrowUp', repeat: true });
    expect(cells()).toBe(initial);
    const move = new KeyboardEvent('keydown', {
      code: 'ArrowDown',
      repeat: true,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(board(), move);
    expect(move.defaultPrevented).toBe(true);
    expect(screen.getByTestId('tetris-score').textContent).toBe('1');
    const buttonKey = new KeyboardEvent('keydown', {
      code: 'Space',
      bubbles: true,
      cancelable: true,
    });
    fireEvent(screen.getByRole('button', { name: 'Pause game' }), buttonKey);
    expect(buttonKey.defaultPrevented).toBe(false);
    fireEvent.keyDown(board(), { code: 'Escape' });
    fireEvent.keyDown(board(), { code: 'Escape', repeat: true });
    expect(screen.getByRole('status').textContent).toContain('Paused');
    fireEvent.keyDown(board(), { code: 'Escape' });
    expect(screen.getByRole('status').textContent).toBe('Playing');
  });
  it('starts fresh after unmounting and renders Korean labels', async () => {
    const view = await renderSolo(<TetrisView />);
    start();
    fireEvent.keyDown(board(), { code: 'Space' });
    expect(
      Number(screen.getByTestId('tetris-score').textContent),
    ).toBeGreaterThan(0);
    view.unmount();
    await act(async () => {
      await i18n.changeLanguage('ko-KR');
    });
    await renderSolo(<TetrisView />);
    expect(screen.getByRole('button', { name: '게임 시작' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '테트리스' })).toBeTruthy();
    expect(screen.getByTestId('tetris-score').textContent).toBe('0');
  });
});
