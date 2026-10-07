import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

import {
  buildFilesRagSourcesPreview,
  FilesRagSourcesArtifact,
} from './FilesRagSourcesArtifact';
import { FilesApiError, getFileDownloadUrl } from '../api/files-api';
import { downloadAuthenticatedContent } from '@miy/platform-web/browser';

const logout = vi.fn();
let token = 'token-1';
beforeEach(() => {
  token = 'token-1';
  vi.clearAllMocks();
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) =>
      options?.name ? `${key}:${options.name}` : key,
  }),
}));

vi.mock('@miy/platform-web/auth-context', () => ({
  useAuth: () => ({
    logout,
    token,
  }),
}));

vi.mock('../api/files-api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/files-api')>();
  return {
    ...actual,
    getFileDownloadUrl: vi
      .fn()
      .mockResolvedValue({ url: '/fresh-download/file-1' }),
  };
});

vi.mock('@miy/platform-web/browser', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('@miy/platform-web/browser')>();
  return {
    ...actual,
    downloadAuthenticatedContent: vi.fn().mockResolvedValue(undefined),
  };
});

function renderSources(content: string) {
  render(
    <MemoryRouter initialEntries={['/apps/files/chat']}>
      <Routes>
        <Route
          path="/apps/files/chat"
          element={<FilesRagSourcesArtifact content={content} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('FilesRagSourcesArtifact', () => {
  it('builds a compact filename preview for the collapsed artifact card', () => {
    expect(
      buildFilesRagSourcesPreview(
        JSON.stringify({
          version: 1,
          sources: [
            { ref: 'F1', file_id: 'file-1', filename: 'roadmap.pdf' },
            { ref: 'F2', file_id: 'file-2', filename: 'release-notes.md' },
          ],
        }),
      ),
    ).toBe('roadmap.pdf · release-notes.md');
    expect(buildFilesRagSourcesPreview('not-json')).toBeNull();
  });

  it('renders document citations and requests a fresh ACL-checked download URL', async () => {
    renderSources(
      JSON.stringify({
        version: 1,
        sources: [
          {
            ref: 'F1',
            file_id: 'file-1',
            filename: 'roadmap.pdf',
            locator: 'page 4',
            methods: ['bm25', 'dense_vector'],
          },
        ],
      }),
    );

    expect(screen.getByText('F1')).toBeTruthy();
    expect(screen.getByText('roadmap.pdf')).toBeTruthy();
    expect(screen.getByText('page 4')).toBeTruthy();
    expect(screen.getByText('bm25')).toBeTruthy();

    fireEvent.click(
      screen.getByRole('button', {
        name: 'files.chat.sources.download:roadmap.pdf',
      }),
    );

    await waitFor(() => {
      expect(getFileDownloadUrl).toHaveBeenCalledWith('token-1', 'file-1');
      expect(downloadAuthenticatedContent).toHaveBeenCalledWith(
        'token-1',
        '/fresh-download/file-1',
        'roadmap.pdf',
      );
    });
  });

  it('fails closed when the artifact payload is malformed', () => {
    renderSources('not-json');
    expect(screen.getByText('files.chat.sources.invalid')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});

afterEach(() => cleanup());

const content = JSON.stringify({
  version: 1,
  sources: [{ ref: 'F1', file_id: 'file-1', filename: 'a.txt' }],
});
it.each(['token', 'content', 'unmount'] as const)(
  'discards late artifact download after %s change',
  async (boundary) => {
    let resolve!: (value: { url: string }) => void;
    vi.mocked(getFileDownloadUrl).mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const r = render(<FilesRagSourcesArtifact content={content} />);
    fireEvent.click(screen.getByRole('button'));
    if (boundary === 'unmount') r.unmount();
    else {
      if (boundary === 'token') token = 'token-2';
      r.rerender(
        <FilesRagSourcesArtifact
          content={boundary === 'content' ? 'not-json' : content}
        />,
      );
    }
    await act(async () => {
      resolve({ url: '/old' });
    });
    expect(downloadAuthenticatedContent).not.toHaveBeenCalled();
  },
);
it('does not log out the new session after an old artifact 401', async () => {
  let reject!: (reason: unknown) => void;
  vi.mocked(getFileDownloadUrl).mockReturnValueOnce(
    new Promise((_r, j) => {
      reject = j;
    }),
  );
  const r = render(<FilesRagSourcesArtifact content={content} />);
  fireEvent.click(screen.getByRole('button'));
  token = 'token-2';
  r.rerender(<FilesRagSourcesArtifact content={content} />);
  await act(async () => {
    reject(new FilesApiError(401, 'old'));
  });
  expect(logout).not.toHaveBeenCalled();
});
