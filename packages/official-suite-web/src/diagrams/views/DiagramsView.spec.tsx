import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import { formatDateTime } from '@miy/platform-web/time/time-utils';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  archiveDiagram,
  createDiagram,
  getDiagram,
  listDiagramsHub,
  updateDiagram,
  type DiagramDetail,
} from '../api/diagrams-api';
import { DiagramsView } from './DiagramsView';

const translation = vi.hoisted(() => ({
  t: (key: string, values?: { date?: string }) =>
    values?.date ? `${key}: ${values.date}` : key,
  i18n: { language: 'en-US' },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => translation }));
vi.mock('../api/diagrams-api', async (original) => ({
  ...(await original<typeof import('../api/diagrams-api')>()),
  archiveDiagram: vi.fn(),
  createDiagram: vi.fn(),
  getDiagram: vi.fn(),
  listDiagramsHub: vi.fn(),
  updateDiagram: vi.fn(),
}));

const detail: DiagramDetail = {
  id: 'diagram-1',
  title: 'Team map',
  visibility: 'personal',
  version: 3,
  created_by_id: 'user-1',
  created_by_name: 'Member',
  created_at: '2026-10-06T09:30:00Z',
  updated_at: '2026-10-06T09:30:00Z',
  archived_at: null,
  preview_available: false,
  preview_url: null,
  can_edit: true,
  can_manage: true,
  xml: '<mxfile />',
};
const context = (token = 'first-session') =>
  ({
    token,
    status: 'authenticated',
    user: { time_zone: 'America/New_York' },
  }) as AuthContextValue;
const view = (path: string, token = 'first-session') => (
  <AuthContext.Provider value={context(token)}>
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/apps/diagrams" element={<DiagramsView />} />
        <Route
          path="/apps/diagrams/diagrams/:diagramId"
          element={<DiagramsView />}
        />
      </Routes>
    </MemoryRouter>
  </AuthContext.Provider>
);
beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  vi.mocked(getDiagram).mockResolvedValue(detail);
  vi.mocked(listDiagramsHub).mockResolvedValue({
    items: [detail],
    total: 1,
    view: 'all',
    page: 1,
    page_size: 200,
  });
  vi.mocked(updateDiagram).mockResolvedValue({ ...detail, version: 4 });
});
afterEach(cleanup);

it('uses the active platform session and user time zone in the hub', async () => {
  render(view('/apps/diagrams'));
  await screen.findByText('Team map');
  expect(listDiagramsHub).toHaveBeenCalledWith(
    'first-session',
    expect.objectContaining({ view: 'all' }),
  );
  const date = formatDateTime(detail.updated_at, {
    fallback: '-',
    locale: 'en-US',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
  });
  expect(screen.getByText(`diagrams.updated: ${date}`)).toBeTruthy();
});

it('surfaces an API denial without rendering retained editor contents', async () => {
  vi.mocked(getDiagram).mockRejectedValue(new Error('Access withdrawn'));
  render(view('/apps/diagrams/diagrams/diagram-1'));
  await screen.findByText('Access withdrawn');
  expect(screen.queryByTitle('apps:diagrams.editorTitle')).toBeNull();
});

it('accepts draw.io changes only from the current iframe and exact origin', async () => {
  render(view('/apps/diagrams/diagrams/diagram-1'));
  const frame = (await screen.findByTitle(
    'apps:diagrams.editorTitle',
  )) as HTMLIFrameElement;
  const origin = new URL(frame.src).origin;
  const payload = JSON.stringify({
    event: 'export',
    format: 'png',
    xml: '<mxfile>new</mxfile>',
    data: 'data:image/png;base64,AA==',
  });
  const send = (source: Window | null, messageOrigin: string, data: unknown) =>
    fireEvent(
      window,
      new MessageEvent('message', { source, origin: messageOrigin, data }),
    );
  send(window, origin, payload);
  send(frame.contentWindow, 'https://unrelated.example.test', payload);
  send(frame.contentWindow, origin, '{invalid');
  expect(updateDiagram).not.toHaveBeenCalled();
  send(frame.contentWindow, origin, payload);
  await waitFor(() =>
    expect(updateDiagram).toHaveBeenCalledWith('first-session', 'diagram-1', {
      version: 3,
      xml: '<mxfile>new</mxfile>',
      preview_png_data_url: 'data:image/png;base64,AA==',
    }),
  );
});

it('does not write read-only documents even for a valid iframe message', async () => {
  vi.mocked(getDiagram).mockResolvedValue({
    ...detail,
    can_edit: false,
    can_manage: false,
  });
  render(view('/apps/diagrams/diagrams/diagram-1'));
  const frame = (await screen.findByTitle(
    'apps:diagrams.editorTitle',
  )) as HTMLIFrameElement;
  fireEvent(
    window,
    new MessageEvent('message', {
      source: frame.contentWindow,
      origin: new URL(frame.src).origin,
      data: JSON.stringify({ event: 'export', xml: '<mxfile>new</mxfile>' }),
    }),
  );
  expect(updateDiagram).not.toHaveBeenCalled();
});

it('discards the old editor and its pending response when the active session changes', async () => {
  let finish!: (value: DiagramDetail) => void;
  vi.mocked(getDiagram)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce({ ...detail, title: 'Current session map' });
  const rendered = render(view('/apps/diagrams/diagrams/diagram-1'));
  rendered.rerender(
    view('/apps/diagrams/diagrams/diagram-1', 'second-session'),
  );
  await screen.findByDisplayValue('Current session map');
  finish(detail);
  await waitFor(() =>
    expect(getDiagram).toHaveBeenCalledWith('second-session', 'diagram-1'),
  );
  expect(screen.queryByDisplayValue('Team map')).toBeNull();
});

it('discards a previous session hub response after the current session has loaded', async () => {
  const oldResponse = {
    items: [detail],
    total: 1,
    view: 'all' as const,
    page: 1,
    page_size: 200,
  };
  let finish!: (value: typeof oldResponse) => void;
  vi.mocked(listDiagramsHub)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockResolvedValueOnce({
      ...oldResponse,
      items: [{ ...detail, id: 'diagram-2', title: 'Current session map' }],
    });
  const rendered = render(view('/apps/diagrams'));
  await waitFor(() => expect(listDiagramsHub).toHaveBeenCalledTimes(1));
  rendered.rerender(view('/apps/diagrams', 'second-session'));
  await screen.findByText('Current session map');
  await act(async () => {
    finish(oldResponse);
  });
  expect(screen.queryByText('Team map')).toBeNull();
  expect(screen.getByText('Current session map')).toBeTruthy();
});

it('ignores an old iframe message after the active session changes', async () => {
  const rendered = render(view('/apps/diagrams/diagrams/diagram-1'));
  const oldFrame = (await screen.findByTitle(
    'apps:diagrams.editorTitle',
  )) as HTMLIFrameElement;
  const oldWindow = oldFrame.contentWindow;
  const origin = new URL(oldFrame.src).origin;
  rendered.rerender(
    view('/apps/diagrams/diagrams/diagram-1', 'second-session'),
  );
  const currentFrame = (await screen.findByTitle(
    'apps:diagrams.editorTitle',
  )) as HTMLIFrameElement;
  expect(currentFrame).not.toBe(oldFrame);
  const data = JSON.stringify({
    event: 'export',
    xml: '<mxfile>old-session</mxfile>',
  });
  fireEvent(
    window,
    new MessageEvent('message', { source: oldWindow, origin, data }),
  );
  expect(updateDiagram).not.toHaveBeenCalled();
  fireEvent(
    window,
    new MessageEvent('message', {
      source: currentFrame.contentWindow,
      origin,
      data: JSON.stringify({
        event: 'export',
        xml: '<mxfile>current-session</mxfile>',
      }),
    }),
  );
  await waitFor(() =>
    expect(updateDiagram).toHaveBeenCalledWith('second-session', 'diagram-1', {
      version: 3,
      xml: '<mxfile>current-session</mxfile>',
      preview_png_data_url: null,
    }),
  );
});

it('does not navigate the new session when a previous session create completes', async () => {
  let finish!: (value: DiagramDetail) => void;
  vi.mocked(createDiagram).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const rendered = render(view('/apps/diagrams'));
  await screen.findByText('Team map');
  fireEvent(window, new Event('diagrams:create'));
  await waitFor(() =>
    expect(createDiagram).toHaveBeenCalledWith(
      'first-session',
      expect.objectContaining({ visibility: 'personal' }),
    ),
  );
  vi.mocked(listDiagramsHub).mockResolvedValueOnce({
    items: [{ ...detail, id: 'diagram-2', title: 'Current session map' }],
    total: 1,
    view: 'all',
    page: 1,
    page_size: 200,
  });
  rendered.rerender(view('/apps/diagrams', 'second-session'));
  await screen.findByText('Current session map');
  await act(async () => {
    finish(detail);
  });
  expect(screen.getByText('Current session map')).toBeTruthy();
  expect(screen.queryByTitle('apps:diagrams.editorTitle')).toBeNull();
  expect(getDiagram).not.toHaveBeenCalled();
});

it('does not leave the current editor when a previous session archive completes', async () => {
  let finish!: () => void;
  vi.mocked(archiveDiagram).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.mocked(getDiagram)
    .mockResolvedValueOnce(detail)
    .mockResolvedValueOnce({ ...detail, title: 'Current session map' });
  const rendered = render(view('/apps/diagrams/diagrams/diagram-1'));
  await screen.findByDisplayValue('Team map');
  fireEvent.click(screen.getByTitle('apps:diagrams.archive'));
  await waitFor(() =>
    expect(archiveDiagram).toHaveBeenCalledWith('first-session', 'diagram-1'),
  );
  rendered.rerender(
    view('/apps/diagrams/diagrams/diagram-1', 'second-session'),
  );
  await screen.findByDisplayValue('Current session map');
  await act(async () => {
    finish();
  });
  expect(screen.getByDisplayValue('Current session map')).toBeTruthy();
  expect(screen.getByTitle('apps:diagrams.editorTitle')).toBeTruthy();
  expect(listDiagramsHub).not.toHaveBeenCalled();
});
