import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  archiveBentoDocument,
  createBentoDocument,
  getBentoDocument,
  editBentoDocumentWithAi,
  getBentoAiJob,
  listBentoDocuments,
  updateBentoDocument,
  type BentoDocumentDetail,
  type BentoHubResponse,
} from '../api/bento-api';
import { BentoView } from './BentoView';

const translation = vi.hoisted(() => ({
  t: (key: string) => key,
  i18n: { language: 'en-US' },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => translation }));
vi.mock('../api/bento-api', async (original) => ({
  ...(await original<typeof import('../api/bento-api')>()),
  createBentoDocument: vi.fn(),
  listBentoDocuments: vi.fn(),
  getBentoDocument: vi.fn(),
  updateBentoDocument: vi.fn(),
  archiveBentoDocument: vi.fn(),
  editBentoDocumentWithAi: vi.fn(),
  getBentoAiJob: vi.fn(),
}));
vi.mock('./bento-embed-protocol', async (original) => ({
  ...(await original<typeof import('./bento-embed-protocol')>()),
  currentBentoEmbedConfig: () => ({
    src: 'https://bento.example/?miy-embed=1',
    origin: 'https://bento.example',
  }),
}));

const detail: BentoDocumentDetail = {
  id: 'deck-one',
  title: 'Current account presentation',
  visibility: 'personal',
  version: 2,
  created_by_id: 'owner',
  created_by_name: 'Owner',
  created_at: '2026-10-06T09:00:00Z',
  updated_at: '2026-10-06T09:00:00Z',
  archived_at: null,
  can_edit: true,
  can_manage: true,
  document_json: '{}',
};
const response = (items: BentoDocumentDetail[] = []): BentoHubResponse => ({
  items,
  view: 'all',
  page: 1,
  page_size: 200,
  total: items.length,
});
let sessionToken: string | null = null;
let sessionEpoch = 0;
let sessionGuard = () => false;
const context = (token: string, withGuard = true) => {
  if (sessionToken !== token) {
    sessionToken = token;
    const epoch = ++sessionEpoch;
    sessionGuard = () => sessionEpoch === epoch && sessionToken === token;
  }
  return {
    token,
    status: 'authenticated',
    user: { id: 'owner', time_zone: 'UTC' },
    ...(withGuard ? { isSessionCurrent: sessionGuard } : {}),
  } as AuthContextValue;
};
function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}
const view = (token: string, path = '/apps/bento', withGuard = true) => (
  <AuthContext.Provider value={context(token, withGuard)}>
    <MemoryRouter initialEntries={[path]}>
      <Location />
      <Link to="/elsewhere">leave app</Link>
      <Routes>
        <Route path="/apps/bento" element={<BentoView />} />
        <Route
          path="/apps/bento/presentations/:documentId"
          element={<BentoView />}
        />
        <Route path="/elsewhere" element={<div>Other app</div>} />
      </Routes>
    </MemoryRouter>
  </AuthContext.Provider>
);
beforeEach(() => {
  vi.clearAllMocks();
  sessionToken = null;
  sessionEpoch = 0;
  sessionGuard = () => false;
  vi.mocked(listBentoDocuments).mockResolvedValue(response());
  vi.mocked(createBentoDocument).mockResolvedValue(detail);
  vi.mocked(getBentoDocument).mockResolvedValue(detail);
  vi.mocked(updateBentoDocument).mockResolvedValue({ ...detail, version: 3 });
  vi.mocked(archiveBentoDocument).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it('does not show a previous account list that resolves after a session change', async () => {
  let finish!: (value: BentoHubResponse) => void;
  vi.mocked(listBentoDocuments).mockImplementation(async (token) =>
    token === 'previous-session'
      ? await new Promise<BentoHubResponse>((resolve) => {
          finish = resolve;
        })
      : response([detail]),
  );
  const rendered = render(view('previous-session'));
  rendered.rerender(view('current-session'));
  await screen.findByText(detail.title);
  await act(async () =>
    finish(
      response([
        {
          ...detail,
          id: 'previous-deck',
          title: 'Previous account presentation',
        },
      ]),
    ),
  );
  expect(screen.queryByText('Previous account presentation')).toBeNull();
  expect(screen.getByText(detail.title)).toBeTruthy();
});

it('does not navigate the next account when an earlier create completes', async () => {
  let finish!: (value: BentoDocumentDetail) => void;
  vi.mocked(createBentoDocument).mockImplementation(
    async () =>
      await new Promise<BentoDocumentDetail>((resolve) => {
        finish = resolve;
      }),
  );
  const rendered = render(view('previous-session'));
  fireEvent.click(
    screen.getAllByRole('button', { name: 'apps:bento.createPersonal' })[0],
  );
  expect(createBentoDocument).toHaveBeenCalledTimes(1);
  rendered.rerender(view('current-session'));
  await act(async () => finish(detail));
  expect(screen.getByTestId('location').textContent).toBe('/apps/bento');
});

it('keeps a newer search result when an earlier search resolves last', async () => {
  let finish!: (value: BentoHubResponse) => void;
  vi.mocked(listBentoDocuments).mockImplementation(async (_token, params) =>
    params.q
      ? response([detail])
      : await new Promise<BentoHubResponse>((resolve) => {
          finish = resolve;
        }),
  );
  render(view('current-session'));
  fireEvent.change(screen.getByPlaceholderText('apps:bento.search'), {
    target: { value: 'new query' },
  });
  await screen.findByText(detail.title);
  await act(async () =>
    finish(response([{ ...detail, title: 'Obsolete search' }])),
  );
  expect(screen.queryByText('Obsolete search')).toBeNull();
  expect(screen.getByText(detail.title)).toBeTruthy();
});

it('does not submit an import after its file read outlives the session', async () => {
  let finish!: (value: string) => void;
  const file = {
    text: () =>
      new Promise<string>((resolve) => {
        finish = resolve;
      }),
  };
  const rendered = render(view('previous-session'));
  const input = document.querySelector('input[type=file]');
  if (!input) throw new Error('Missing file input');
  fireEvent.change(input, { target: { files: [file] } });
  rendered.rerender(view('current-session'));
  await act(async () => finish('<html></html>'));
  expect(createBentoDocument).not.toHaveBeenCalled();
});

it('preserves the normal create payload and canonical route', async () => {
  render(view('current-session'));
  fireEvent.click(
    screen.getAllByRole('button', { name: 'apps:bento.createPersonal' })[0],
  );
  await screen.findByTitle('bento.editorTitle');
  expect(createBentoDocument).toHaveBeenCalledExactlyOnceWith(
    'current-session',
    {
      title: 'apps:bento.untitled',
      visibility: 'personal',
      company_admin_read_acknowledged: false,
    },
  );
  expect(screen.getByTestId('location').textContent).toBe(
    '/apps/bento/presentations/deck-one',
  );
});

const changed = {
  channel: 'miy:bento',
  version: 2,
  type: 'save-request',
  documentJson: '{"slides":[1]}',
};
function message(
  frame: HTMLIFrameElement,
  data = changed,
  origin = 'https://bento.example',
  source: MessageEventSource | null = frame.contentWindow,
) {
  fireEvent(window, new MessageEvent('message', { origin, source, data }));
}

it.each(['origin', 'window', 'protocol', 'permission'] as const)(
  'does not save an iframe message without the current %s boundary',
  async (boundary) => {
    if (boundary === 'permission')
      vi.mocked(getBentoDocument).mockResolvedValue({
        ...detail,
        can_edit: false,
        can_manage: false,
      });
    render(view('current-session', '/apps/bento/presentations/deck-one'));
    const frame = (await screen.findByTitle(
      'bento.editorTitle',
    )) as HTMLIFrameElement;
    vi.useFakeTimers();
    message(
      frame,
      boundary === 'protocol' ? { ...changed, version: 1 } : changed,
      boundary === 'origin' ? 'https://other.example' : 'https://bento.example',
      boundary === 'window' ? window : frame.contentWindow,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(updateBentoDocument).not.toHaveBeenCalled();
  },
);

it('saves valid iframe edits with the current document version', async () => {
  render(view('current-session', '/apps/bento/presentations/deck-one'));
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(updateBentoDocument).toHaveBeenCalledExactlyOnceWith(
    'current-session',
    'deck-one',
    { version: 2, document_json: changed.documentJson },
  );
});

it('drops queued edits after a session change while preserving the already sent request', async () => {
  let finish!: (value: BentoDocumentDetail) => void;
  vi.mocked(updateBentoDocument).mockImplementationOnce(
    async () =>
      await new Promise<BentoDocumentDetail>((resolve) => {
        finish = resolve;
      }),
  );
  const path = '/apps/bento/presentations/deck-one';
  const rendered = render(view('previous-session', path));
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  message(frame, { ...changed, documentJson: '{"slides":[2]}' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(updateBentoDocument).toHaveBeenCalledTimes(1);
  rendered.rerender(view('current-session', path));
  await act(async () =>
    finish({ ...detail, version: 3, document_json: changed.documentJson }),
  );
  expect(updateBentoDocument).toHaveBeenCalledTimes(1);
});

it.each(['hub', 'other app', 'debounced edit'])(
  'finishes accepted queued edits after same-session navigation to %s',
  async (destination) => {
    let finish!: (value: BentoDocumentDetail) => void;
    vi.mocked(updateBentoDocument).mockImplementationOnce(
      () =>
        new Promise<BentoDocumentDetail>((resolve) => {
          finish = resolve;
        }),
    );
    render(view('current-session', '/apps/bento/presentations/deck-one'));
    const frame = (await screen.findByTitle(
      'bento.editorTitle',
    )) as HTMLIFrameElement;
    vi.useFakeTimers();
    message(frame);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    message(frame, {
      ...changed,
      type:
        destination === 'debounced edit' ? 'document-changed' : 'save-request',
      documentJson: '{"slides":[2]}',
    });
    if (destination !== 'debounced edit') {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    }
    expect(updateBentoDocument).toHaveBeenCalledTimes(1);
    fireEvent.click(
      destination === 'hub'
        ? screen.getByTitle('bento.back')
        : screen.getByRole('link', { name: 'leave app' }),
    );
    await act(async () =>
      finish({ ...detail, version: 3, document_json: changed.documentJson }),
    );
    expect(updateBentoDocument).toHaveBeenCalledTimes(2);
    expect(updateBentoDocument).toHaveBeenNthCalledWith(
      2,
      'current-session',
      'deck-one',
      {
        version: 3,
        document_json: '{"slides":[2]}',
      },
    );
  },
);

it('does not navigate the next session after an old archive completes', async () => {
  let finish!: () => void;
  vi.mocked(archiveBentoDocument).mockImplementationOnce(
    async () =>
      await new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const path = '/apps/bento/presentations/deck-one';
  const rendered = render(view('previous-session', path));
  await screen.findByTitle('bento.editorTitle');
  fireEvent.click(screen.getByTitle('bento.archive'));
  await act(async () => Promise.resolve());
  expect(archiveBentoDocument).toHaveBeenCalledTimes(1);
  rendered.rerender(view('current-session', path));
  await act(async () => finish());
  expect(screen.getByTestId('location').textContent).toBe(path);
});

it.each(['rotated back', 'same token relogin', 'missing snapshot'])(
  'does not drain a retired queue across %s',
  async (boundary) => {
    let finish!: (value: BentoDocumentDetail) => void;
    vi.mocked(updateBentoDocument).mockImplementationOnce(
      () =>
        new Promise<BentoDocumentDetail>((resolve) => {
          finish = resolve;
        }),
    );
    const path = '/apps/bento/presentations/deck-one';
    const rendered = render(
      view('previous-session', path, boundary !== 'missing snapshot'),
    );
    const frame = (await screen.findByTitle(
      'bento.editorTitle',
    )) as HTMLIFrameElement;
    vi.useFakeTimers();
    message(frame);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    message(frame, { ...changed, documentJson: '{"slides":[2]}' });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    if (boundary === 'missing snapshot') {
      fireEvent.click(screen.getByRole('link', { name: 'leave app' }));
    } else {
      if (boundary === 'rotated back')
        rendered.rerender(view('current-session', path));
      else sessionToken = null;
      rendered.rerender(view('previous-session', path));
    }
    await act(async () =>
      finish({ ...detail, version: 3, document_json: changed.documentJson }),
    );
    expect(updateBentoDocument).toHaveBeenCalledTimes(1);
    if (boundary !== 'missing snapshot') {
      const currentFrame = screen.getByTitle(
        'bento.editorTitle',
      ) as HTMLIFrameElement;
      message(currentFrame, { ...changed, documentJson: '{"slides":[3]}' });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(updateBentoDocument).toHaveBeenNthCalledWith(
        2,
        'previous-session',
        'deck-one',
        {
          version: 2,
          document_json: '{"slides":[3]}',
        },
      );
    }
  },
);

it('keeps the pending debounce when only the translation callback changes', async () => {
  const rendered = render(
    view('current-session', '/apps/bento/presentations/deck-one'),
  );
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame, { ...changed, type: 'document-changed' });
  const previousT = translation.t;
  try {
    translation.t = (key: string) => key;
    rendered.rerender(
      view('current-session', '/apps/bento/presentations/deck-one'),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(updateBentoDocument).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(650);
    });
    expect(updateBentoDocument).toHaveBeenCalledExactlyOnceWith(
      'current-session',
      'deck-one',
      {
        version: 2,
        document_json: changed.documentJson,
      },
    );
  } finally {
    translation.t = previousT;
  }
});

it('blocks a retired queue when credentials change after the editor has already unmounted', async () => {
  let finish!: (value: BentoDocumentDetail) => void;
  vi.mocked(updateBentoDocument).mockImplementationOnce(
    () =>
      new Promise<BentoDocumentDetail>((resolve) => {
        finish = resolve;
      }),
  );
  const path = '/apps/bento/presentations/deck-one';
  const rendered = render(view('previous-session', path));
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  message(frame, { ...changed, documentJson: '{"slides":[2]}' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  fireEvent.click(screen.getByRole('link', { name: 'leave app' }));
  expect(screen.queryByTitle('bento.editorTitle')).toBeNull();
  rendered.rerender(view('current-session', path));
  await act(async () =>
    finish({ ...detail, version: 3, document_json: changed.documentJson }),
  );
  expect(updateBentoDocument).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('location').textContent).toBe('/elsewhere');
});

it('consumes a cancelled debounce before the existing AI current-document save', async () => {
  vi.mocked(editBentoDocumentWithAi).mockResolvedValue({
    id: 'ai-job',
  } as Awaited<ReturnType<typeof editBentoDocumentWithAi>>);
  vi.mocked(getBentoAiJob).mockResolvedValue({ status: 'running' } as Awaited<
    ReturnType<typeof getBentoAiJob>
  >);
  render(view('current-session', '/apps/bento/presentations/deck-one'));
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame, { ...changed, type: 'ready' });
  message(frame, { ...changed, type: 'document-changed' });
  fireEvent.click(screen.getByTitle('bento.aiEdit'));
  fireEvent.change(
    screen.getByPlaceholderText('bento.aiEditPromptPlaceholder'),
    { target: { value: 'Adjust the layout' } },
  );
  fireEvent.click(screen.getByRole('button', { name: 'bento.aiEditApply' }));
  await act(async () => {
    await Promise.resolve();
  });
  message(frame, { ...changed, documentJson: '{"slides":[2]}' });
  await act(async () => {
    await Promise.resolve();
  });
  expect(editBentoDocumentWithAi).toHaveBeenCalledTimes(1);
  expect(updateBentoDocument).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('link', { name: 'leave app' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(updateBentoDocument).toHaveBeenCalledTimes(1);
});

it('keeps a failed save unsaved without advancing its version', async () => {
  vi.mocked(updateBentoDocument).mockRejectedValueOnce(
    new Error('Synthetic save conflict'),
  );
  render(view('current-session', '/apps/bento/presentations/deck-one'));
  const frame = (await screen.findByTitle(
    'bento.editorTitle',
  )) as HTMLIFrameElement;
  vi.useFakeTimers();
  message(frame);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByText('Synthetic save conflict')).toBeTruthy();
  expect(screen.getByText('bento.error')).toBeTruthy();
  message(frame, { ...changed, documentJson: '{"slides":[2]}' });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(updateBentoDocument).toHaveBeenNthCalledWith(
    2,
    'current-session',
    'deck-one',
    {
      version: 2,
      document_json: '{"slides":[2]}',
    },
  );
});
