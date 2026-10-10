import { pmsHelpGuideRegistration } from '@miy/official-suite-web';
import { useRealtime } from '@miy/platform-web/realtime';
import { render, screen } from '@testing-library/react';
import {
  AppContent,
  DefaultShellRealtimeProvider,
} from '@miy/web-official-suite-bridge';
import { expect, it, vi } from 'vitest';

import OfficialSuiteRoot from './OfficialSuiteRoot';

vi.mock('@miy/web-official-suite-bridge', async (original) => ({
  ...(await original<typeof import('@miy/web-official-suite-bridge')>()),
  AppContent: vi.fn(() => null),
}));

it('selects PMS help explicitly for both suite shell routes and the help modal', () => {
  render(<OfficialSuiteRoot />);
  const props = vi.mocked(AppContent).mock.calls[0][0];
  expect(props.helpGuides).toEqual([pmsHelpGuideRegistration]);
  expect(
    props.helpRoutes?.find((route) => route.path === '/help')?.element,
  ).toMatchObject({ props: { guides: props.helpGuides } });
  expect(
    props.helpRoutes?.find((route) => route.path === '/help/pms')?.element,
  ).toMatchObject({ props: { guide: pmsHelpGuideRegistration } });
});

it('uses the live common shell provider and preserves the no-token offline state', () => {
  vi.mocked(AppContent).mockClear();
  render(<OfficialSuiteRoot />);
  const props = vi.mocked(AppContent).mock.calls[0][0];
  expect(props.realtimeEnabled).toBe(true);
  expect(props.realtimeProvider).toBe(DefaultShellRealtimeProvider);
  const Provider = props.realtimeProvider;
  if (!Provider)
    throw new Error('Missing official app realtime context provider');
  const socket = vi.spyOn(globalThis, 'WebSocket');
  function Probe() {
    const { status } = useRealtime();
    return <div data-testid="official-realtime-status">{status}</div>;
  }
  try {
    render(
      <Provider token={null}>
        <Probe />
      </Provider>,
    );
    expect(screen.getByTestId('official-realtime-status').textContent).toBe(
      'offline',
    );
    expect(socket).not.toHaveBeenCalled();
  } finally {
    socket.mockRestore();
  }
});
