import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import { i18n } from '@/src/platform/i18n';
import { TetrisView } from './TetrisView';
vi.mock('@/src/platform/auth/auth-provider', () => ({
  useAuth: () => ({ token: 'test-token' }),
}));
const board = () => screen.getByRole('region', { name: 'Game board' });
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
});
describe('tetris controls and lifecycle', () => {
  it('offers screen controls with the same movement, hold and pause rules', () => {
    render(<TetrisView />);
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
  it('gives a restarted game a full gravity interval', () => {
    render(<TetrisView />);
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
  it('starts with focus and runs a single timer even in StrictMode', () => {
    const view = render(
      <StrictMode>
        <TetrisView />
      </StrictMode>,
    );
    expect(vi.getTimerCount()).toBe(0);
    start();
    expect(document.activeElement).toBe(board());
    expect(vi.getTimerCount()).toBe(1);
    const initial = cells();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(cells()).not.toBe(initial);
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
  it('keeps playing when the window, tab or game loses focus without intercepting outside keys', () => {
    render(
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
  it('consumes game keys only at the board and suppresses repeat for one-shot actions', () => {
    render(<TetrisView />);
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
    const view = render(<TetrisView />);
    start();
    fireEvent.keyDown(board(), { code: 'Space' });
    expect(
      Number(screen.getByTestId('tetris-score').textContent),
    ).toBeGreaterThan(0);
    view.unmount();
    await act(async () => {
      await i18n.changeLanguage('ko-KR');
    });
    render(<TetrisView />);
    expect(screen.getByRole('button', { name: '게임 시작' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '테트리스' })).toBeTruthy();
    expect(screen.getByTestId('tetris-score').textContent).toBe('0');
  });
});
