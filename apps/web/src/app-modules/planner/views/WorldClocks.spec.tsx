import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WorldClocks } from './WorldClocks';

function clockText(city: RegExp): string {
  return (
    screen.getByText(city).parentElement?.querySelector('time')?.textContent ??
    ''
  );
}

describe('WorldClocks', () => {
  afterEach(() => vi.useRealTimers());

  it('uses each city time zone across winter and summer daylight saving time', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-15T12:00:00Z'));
    render(<WorldClocks />);

    expect(clockText(/한국 시간|Korea time/)).toContain('21:00:00');
    expect(clockText(/뉴욕 시간|New York, US time/)).toContain('07:00:00');
    expect(clockText(/베를린 시간|Berlin, Germany time/)).toContain('13:00:00');

    vi.setSystemTime(new Date('2026-07-15T12:00:00Z'));
    act(() => window.dispatchEvent(new Event('focus')));
    expect(clockText(/한국 시간|Korea time/)).toContain('21:00:00');
    expect(clockText(/뉴욕 시간|New York, US time/)).toContain('08:00:00');
    expect(clockText(/베를린 시간|Berlin, Germany time/)).toContain('14:00:00');
  });

  it('refreshes after a tick and window focus', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-24T00:00:00Z'));
    render(<WorldClocks />);

    const time = screen.getByText(/09:00:00/);
    expect(time.closest('time')?.getAttribute('datetime')).toBe(
      '2026-09-24T00:00:00.000Z',
    );
    expect(clockText(/뉴욕 시간|New York, US time/)).toContain('20:00:00');
    expect(clockText(/베를린 시간|Berlin, Germany time/)).toContain('02:00:00');

    act(() => vi.advanceTimersByTime(1000));
    expect(clockText(/한국 시간|Korea time/)).toContain('09:00:01');

    vi.setSystemTime(new Date('2026-09-24T15:30:00Z'));
    act(() => window.dispatchEvent(new Event('focus')));
    expect(clockText(/한국 시간|Korea time/)).toContain('00:30:00');
    expect(clockText(/뉴욕 시간|New York, US time/)).toContain('11:30:00');
    expect(clockText(/베를린 시간|Berlin, Germany time/)).toContain('17:30:00');
  });
});
