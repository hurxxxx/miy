import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useConversationViewport } from './conversation-viewport';

const originalScrollTo = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'scrollTo',
);

const frames = new Map<number, FrameRequestCallback>();
let frameId = 0;
function nextFrame() {
  const pending = [...frames.values()];
  frames.clear();
  for (const callback of pending) callback(performance.now());
}

function Conversation({
  id,
  event = 1,
  height = 3000,
  visible = true,
  hidden = false,
  authenticated = true,
}: {
  id: string;
  event?: number;
  height?: number;
  visible?: boolean;
  hidden?: boolean;
  authenticated?: boolean;
}) {
  const viewport = useConversationViewport(
    id,
    event,
    authenticated,
    `${visible}:${hidden}`,
  );
  return visible ? (
    <div
      data-testid="conversation"
      data-height={height}
      data-hidden={hidden}
      ref={viewport.ref}
      onScroll={viewport.onScroll}
    />
  ) : null;
}

beforeEach(() => {
  frames.clear();
  frameId = 0;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    const id = ++frameId;
    frames.set(id, callback);
    return id;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    frames.delete(id);
  });
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(
    function (this: HTMLElement) {
      return this.dataset.hidden === 'true' ? 0 : 300;
    },
  );
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(
    function (this: HTMLElement) {
      return Number(this.dataset.height);
    },
  );
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: function (this: HTMLElement, options: ScrollToOptions) {
      const top = typeof options === 'number' ? options : (options?.top ?? 0);
      this.scrollTop = Math.max(
        0,
        Math.min(top, this.scrollHeight - this.clientHeight),
      );
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  if (originalScrollTo)
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', originalScrollTo);
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo');
});

function scroll(top: number) {
  const node = screen.getByTestId('conversation');
  node.scrollTop = top;
  fireEvent.scroll(node);
}
const top = () => screen.getByTestId('conversation').scrollTop;

it('restores separate reading positions across tasks and the session list without following new events', () => {
  const { rerender } = render(<Conversation id="first" />);
  expect(top()).toBe(2700);
  scroll(420);
  rerender(<Conversation id="second" />);
  expect(top()).toBe(2700);
  scroll(640);
  rerender(<Conversation id="first" />);
  expect(top()).toBe(420);
  rerender(<Conversation id="first" visible={false} />);
  rerender(<Conversation id="first" />);
  expect(top()).toBe(420);
  rerender(<Conversation id="first" event={2} height={3600} />);
  expect(top()).toBe(420);
  rerender(<Conversation id="second" />);
  expect(top()).toBe(640);
});

it('follows new items only after reading at the bottom, including events received on another page', () => {
  const { rerender } = render(<Conversation id="first" />);
  rerender(<Conversation id="first" event={2} height={3600} />);
  expect(top()).toBe(3300);
  scroll(500);
  rerender(<Conversation id="first" event={3} height={4200} />);
  expect(top()).toBe(500);
  scroll(3900);
  rerender(<Conversation id="first" visible={false} />);
  rerender(<Conversation id="first" visible={false} event={4} height={4800} />);
  rerender(<Conversation id="first" event={4} height={4800} />);
  expect(top()).toBe(4500);
});

it('keeps a long-task reading position when the next task fits in one viewport', () => {
  const { rerender } = render(<Conversation id="long" />);
  scroll(420);
  rerender(<Conversation id="short" height={300} />);
  expect(top()).toBe(0);
  rerender(<Conversation id="long" />);
  expect(top()).toBe(420);
});

it('does not replace the visible reading position with hidden mobile panel geometry', () => {
  const { rerender } = render(<Conversation id="first" />);
  scroll(700);
  rerender(<Conversation id="first" hidden />);
  scroll(0);
  rerender(<Conversation id="first" hidden event={2} height={3600} />);
  rerender(<Conversation id="first" event={2} height={3600} />);
  expect(top()).toBe(700);
});

it('restores a CSS-revealed panel after a window resize without another event or React render', () => {
  render(<Conversation id="first" />);
  const node = screen.getByTestId('conversation');
  node.dataset.hidden = 'true';
  fireEvent(window, new Event('resize'));
  nextFrame();
  node.dataset.height = '3600';
  node.dataset.hidden = 'false';
  fireEvent(window, new Event('resize'));
  nextFrame();
  expect(top()).toBe(3300);
  scroll(420);
  node.dataset.hidden = 'true';
  fireEvent(window, new Event('resize'));
  nextFrame();
  node.dataset.height = '4200';
  node.dataset.hidden = 'false';
  fireEvent(window, new Event('resize'));
  nextFrame();
  expect(top()).toBe(420);
});

it('clears saved positions on logout', () => {
  const { rerender } = render(<Conversation id="first" />);
  scroll(420);
  rerender(<Conversation id="first" authenticated={false} visible={false} />);
  rerender(<Conversation id="first" />);
  expect(top()).toBe(2700);
});

it('bounds memory to the most recently visited 100 task positions', () => {
  const { rerender } = render(<Conversation id="first" />);
  scroll(420);
  for (let index = 0; index < 100; index++) {
    rerender(<Conversation id={`visited-${index}`} />);
    scroll(600);
  }
  rerender(<Conversation id="first" />);
  expect(top()).toBe(2700);
  rerender(<Conversation id="visited-99" />);
  expect(top()).toBe(600);
});

it('lets a queued scroll event update reading mode before resize restoration', () => {
  render(<Conversation id="first" />);
  const node = screen.getByTestId('conversation');
  node.dataset.height = '3600';
  // Resize and scroll events are separate rendering steps. The DOM can already
  // reflect a user scroll before React receives its queued scroll event.
  node.scrollTop = 420;
  fireEvent(window, new Event('resize'));
  fireEvent.scroll(node);
  nextFrame();
  expect(top()).toBe(420);
});

it('coalesces resize restoration and cancels it on unmount', () => {
  const { unmount } = render(<Conversation id="first" />);
  fireEvent(window, new Event('resize'));
  fireEvent(window, new Event('resize'));
  expect(frames.size).toBe(1);
  unmount();
  expect(frames.size).toBe(0);
  nextFrame();
});
