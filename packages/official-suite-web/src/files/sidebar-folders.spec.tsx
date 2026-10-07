import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FilesSidebarFolders } from './sidebar-folders';
import { browseFiles, type FileBrowseResponse } from './api/files-api';
let token = 'a';
vi.mock('@miy/platform-web/auth-context', () => ({
  useAuth: () => ({ token }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./api/files-api', () => ({ browseFiles: vi.fn() }));
function response(name: string): FileBrowseResponse {
  return {
    current_folder: null,
    breadcrumbs: [],
    folders: [],
    files: [],
    all_folders: [
      {
        id: name,
        parent_id: null,
        name: `${name}/private`,
        visibility: 'private',
        owner_id: 'a',
        owner_name: 'A',
        can_manage: true,
        created_at: '',
        updated_at: '',
      },
    ],
  };
}
const tree = () => (
  <MemoryRouter>
    <FilesSidebarFolders />
  </MemoryRouter>
);
beforeEach(() => {
  token = 'a';
  vi.clearAllMocks();
});
afterEach(() => cleanup());
it('does not show an old-account folder response after login changes', async () => {
  let resolve!: (v: FileBrowseResponse) => void;
  vi.mocked(browseFiles)
    .mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    )
    .mockResolvedValue(response('new'));
  const r = render(tree());
  token = 'b';
  r.rerender(tree());
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.getByText('new/private')).toBeTruthy();
  await act(async () => {
    resolve(response('old'));
  });
  expect(screen.queryByText('old/private')).toBeNull();
  expect(screen.getByText('new/private')).toBeTruthy();
});
it('retains the latest folder refresh when an earlier refresh fails', async () => {
  let reject!: (e: unknown) => void;
  vi.mocked(browseFiles)
    .mockReturnValueOnce(
      new Promise((_r, j) => {
        reject = j;
      }),
    )
    .mockResolvedValue(response('new'));
  render(tree());
  await act(async () => {
    window.dispatchEvent(new CustomEvent('files:changed'));
  });
  expect(screen.getByText('new/private')).toBeTruthy();
  await act(async () => {
    reject(new Error('old'));
  });
  expect(screen.getByText('new/private')).toBeTruthy();
});
