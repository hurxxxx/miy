import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../api/files-api';
import * as browser from '@miy/platform-web/browser';
import { useFileManagerController } from './useFileManagerController';

const h = vi.hoisted(() => ({
  token: 'a',
  folder: 'a',
  navigate: vi.fn(),
  t: (key: string) => key,
}));
vi.mock('@miy/platform-web/auth-context', () => ({
  useAuth: () => ({ token: h.token, user: { id: h.token } }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: h.t, i18n: { language: 'en' } }),
}));
vi.mock('react-router-dom', () => ({
  useSearchParams: () => [
    new URLSearchParams({ folder: h.folder }),
    h.navigate,
  ],
}));
vi.mock('../file-upload-provider', () => ({
  useFileUploadManager: () => ({
    hasActiveUploads: false,
    startUpload: vi.fn(),
  }),
}));
vi.mock('../api/files-api', async (original) => ({
  ...(await original<typeof api>()),
  browseFiles: vi.fn(),
  createFileFolder: vi.fn(),
  deleteFileFolder: vi.fn(),
  downloadFileArchive: vi.fn(),
  getFileDownloadUrl: vi.fn(),
  getFilePreviewUrl: vi.fn(),
}));
vi.mock('@miy/platform-web/browser', () => ({
  authenticatedContentObjectUrl: vi.fn(),
  downloadAuthenticatedContent: vi.fn(),
  downloadBlobAsFile: vi.fn(),
}));
function pending<T>() {
  let resolve!: (v: T) => void;
  let reject!: (v: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
const file: api.FileItem = {
  id: 'file',
  folder_id: null,
  filename: 'image.png',
  content_type: 'image/png',
  size_bytes: 1,
  visibility: 'private',
  owner_id: 'a',
  owner_name: 'A',
  can_delete: true,
  rag_status: 'disabled',
  rag_updated_at: null,
  created_at: '',
  updated_at: '',
};
const folder: api.FileFolderItem = {
  id: 'a',
  parent_id: null,
  name: 'A',
  visibility: 'private',
  owner_id: 'a',
  owner_name: 'A',
  can_manage: true,
  created_at: '',
  updated_at: '',
};
beforeEach(() => {
  h.token = 'a';
  h.folder = 'a';
  vi.clearAllMocks();
  vi.mocked(api.downloadFileArchive).mockReset();
  vi.mocked(api.browseFiles).mockImplementation(async (_token, id) => ({
    current_folder: { ...folder, id: id ?? 'root' },
    files: [file],
    folders: [],
    all_folders: [],
    breadcrumbs: [],
  }));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

describe('Files manager scope transition state', () => {
  async function selectedArchive() {
    vi.mocked(api.browseFiles).mockImplementation(async (_token, id) => ({
      current_folder: { ...folder, id: id ?? 'root' },
      files: [
        { ...file, id: `${id}-one` },
        { ...file, id: `${id}-two` },
      ],
      folders: [],
      all_folders: [],
      breadcrumbs: [],
    }));
    const r = await setup();
    act(() => r.result.current.setAllVisibleSelected(true));
    return r;
  }

  it.each(['folder', 'token'] as const)(
    'clears retained archive state after %s changes and ignores old completion',
    async (boundary) => {
      const archive = pending<api.FileArchiveDownload>();
      vi.mocked(api.downloadFileArchive).mockReturnValueOnce(archive.promise);
      const r = await selectedArchive();
      let done!: Promise<void>;
      act(() => {
        done = r.result.current.handleBulkDownload();
      });
      expect(r.result.current.bulkAction).toBe('download');
      if (boundary === 'folder') h.folder = 'b';
      else h.token = 'b';
      r.rerender();
      await waitFor(() => expect(api.browseFiles).toHaveBeenCalledTimes(2));
      expect(r.result.current.bulkAction).toBeNull();
      await act(async () => {
        archive.resolve({ blob: new Blob(['old']), filename: 'old.zip' });
        await done;
      });
      expect(browser.downloadBlobAsFile).not.toHaveBeenCalled();
      expect(r.result.current.bulkAction).toBeNull();
    },
  );

  it.each(['success', 'error'] as const)(
    'keeps a newer archive busy when the previous scope completes with %s',
    async (outcome) => {
      const oldArchive = pending<api.FileArchiveDownload>();
      const newArchive = pending<api.FileArchiveDownload>();
      vi.mocked(api.downloadFileArchive)
        .mockReturnValueOnce(oldArchive.promise)
        .mockReturnValueOnce(newArchive.promise);
      const r = await selectedArchive();
      let oldDone!: Promise<void>;
      act(() => {
        oldDone = r.result.current.handleBulkDownload();
      });
      h.folder = 'b';
      r.rerender();
      await waitFor(() => expect(r.result.current.currentFolder?.id).toBe('b'));
      expect(r.result.current.bulkAction).toBeNull();
      act(() => r.result.current.setAllVisibleSelected(true));
      let newDone!: Promise<void>;
      act(() => {
        newDone = r.result.current.handleBulkDownload();
      });
      expect(r.result.current.bulkAction).toBe('download');
      await act(async () => {
        if (outcome === 'success')
          oldArchive.resolve({ blob: new Blob(['old']), filename: 'old.zip' });
        else oldArchive.reject(new Error('old scope error'));
        await oldDone;
      });
      expect(r.result.current.bulkAction).toBe('download');
      expect(r.result.current.error).toBeNull();
      expect(browser.downloadBlobAsFile).not.toHaveBeenCalled();
      const current = { blob: new Blob(['current']), filename: 'current.zip' };
      await act(async () => {
        newArchive.resolve(current);
        await newDone;
      });
      expect(browser.downloadBlobAsFile).toHaveBeenCalledExactlyOnceWith(
        current.blob,
        current.filename,
      );
      expect(r.result.current.bulkAction).toBeNull();
    },
  );

  it.each(['download', 'preview', 'folder-save'] as const)(
    'resets retained %s pending state without waiting for the old request',
    async (kind) => {
      const request = pending<api.FileDownloadResponse>();
      const saving = pending<api.FileFolderItem>();
      if (kind === 'download')
        vi.mocked(api.getFileDownloadUrl).mockReturnValueOnce(request.promise);
      else if (kind === 'preview')
        vi.mocked(api.getFilePreviewUrl).mockReturnValueOnce(request.promise);
      else vi.mocked(api.createFileFolder).mockReturnValueOnce(saving.promise);
      const r = await setup();
      if (kind === 'folder-save') {
        act(() => r.result.current.openCreateFolder());
        act(() => r.result.current.setFolderName('pending'));
      }
      let done!: Promise<void>;
      act(() => {
        done =
          kind === 'download'
            ? r.result.current.handleDownload(file)
            : kind === 'preview'
              ? r.result.current.handlePreview(file)
              : r.result.current.handleFolderSubmit();
      });
      expect(
        kind === 'download'
          ? r.result.current.busyId
          : kind === 'preview'
            ? r.result.current.previewBusyId
            : r.result.current.savingFolder,
      ).toBe(kind === 'folder-save' ? true : file.id);
      h.token = 'b';
      r.rerender();
      await waitFor(() => expect(api.browseFiles).toHaveBeenCalledTimes(2));
      expect(r.result.current.busyId).toBeNull();
      expect(r.result.current.previewBusyId).toBeNull();
      expect(r.result.current.savingFolder).toBe(false);
      await act(async () => {
        if (kind === 'folder-save') saving.resolve(folder);
        else request.resolve({ url: '/old' });
        await done;
      });
      expect(r.result.current.busyId).toBeNull();
      expect(r.result.current.previewBusyId).toBeNull();
      expect(r.result.current.savingFolder).toBe(false);
      expect(browser.downloadAuthenticatedContent).not.toHaveBeenCalled();
      expect(browser.authenticatedContentObjectUrl).not.toHaveBeenCalled();
    },
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
async function setup() {
  const r = renderHook(() => useFileManagerController());
  await waitFor(() => expect(r.result.current.loadState).toBe('ready'));
  return r;
}
describe('Files manager lifetime', () => {
  it.each(['folder', 'token', 'unmount'] as const)(
    'does not refresh or publish old folder creation after %s changes',
    async (boundary) => {
      const p = pending<api.FileFolderItem>();
      vi.mocked(api.createFileFolder).mockReturnValue(p.promise);
      const r = await setup();
      act(() => r.result.current.openCreateFolder());
      act(() => r.result.current.setFolderName('new'));
      let done!: Promise<void>;
      act(() => {
        done = r.result.current.handleFolderSubmit();
      });
      const changed = vi.fn();
      window.addEventListener('files:changed', changed);
      if (boundary === 'unmount') r.unmount();
      else {
        if (boundary === 'token') h.token = 'b';
        else h.folder = 'b';
        r.rerender();
        await waitFor(() => expect(api.browseFiles).toHaveBeenCalledTimes(2));
      }
      const count = vi.mocked(api.browseFiles).mock.calls.length;
      await act(async () => {
        p.resolve(folder);
        await done;
      });
      window.removeEventListener('files:changed', changed);
      expect(api.browseFiles).toHaveBeenCalledTimes(count);
      expect(changed).not.toHaveBeenCalled();
    },
  );
  it('does not navigate back from a late current-folder deletion', async () => {
    const p = pending<void>();
    vi.mocked(api.deleteFileFolder).mockReturnValue(p.promise);
    const r = await setup();
    let done!: Promise<void>;
    act(() => {
      done = r.result.current.handleDeleteFolder(folder);
    });
    h.folder = 'b';
    r.rerender();
    await act(async () => {
      p.resolve();
      await done;
    });
    expect(h.navigate).not.toHaveBeenCalled();
    expect(r.result.current.currentFolder?.id).toBe('b');
  });
  it.each(['download', 'preview'] as const)(
    'does not start old %s content request after changing login',
    async (kind) => {
      const p = pending<api.FileDownloadResponse>();
      vi.mocked(
        kind === 'download' ? api.getFileDownloadUrl : api.getFilePreviewUrl,
      ).mockReturnValue(p.promise);
      const r = await setup();
      let done!: Promise<void>;
      act(() => {
        done =
          kind === 'download'
            ? r.result.current.handleDownload(file)
            : r.result.current.handlePreview(file);
      });
      h.token = 'b';
      r.rerender();
      await act(async () => {
        p.resolve({ url: '/old' });
        await done;
      });
      expect(browser.downloadAuthenticatedContent).not.toHaveBeenCalled();
      expect(browser.authenticatedContentObjectUrl).not.toHaveBeenCalled();
    },
  );
  it('ignores a stale preview error after a new login', async () => {
    const p = pending<api.FileDownloadResponse>();
    vi.mocked(api.getFilePreviewUrl).mockReturnValue(p.promise);
    const r = await setup();
    let done!: Promise<void>;
    act(() => {
      done = r.result.current.handlePreview(file);
    });
    h.token = 'b';
    r.rerender();
    await act(async () => {
      p.reject(new Error('old private error'));
      await done;
    });
    expect(r.result.current.error).toBeNull();
  });
  it('does not submit a retained mutation callback after unmount', async () => {
    const r = await setup();
    act(() => r.result.current.openCreateFolder());
    const retained = r.result.current.handleFolderSubmit;
    r.unmount();
    await retained();
    expect(api.createFileFolder).not.toHaveBeenCalled();
  });
  it('continues current folder creation and reload normally', async () => {
    vi.mocked(api.createFileFolder).mockResolvedValue(folder);
    const r = await setup();
    act(() => r.result.current.openCreateFolder());
    act(() => r.result.current.setFolderName('new'));
    await act(async () => {
      await r.result.current.handleFolderSubmit();
    });
    expect(api.createFileFolder).toHaveBeenCalledTimes(1);
    expect(api.browseFiles).toHaveBeenCalledTimes(2);
    expect(r.result.current.folderDialog).toBeNull();
  });
});

it.each(['token', 'unmount'] as const)(
  'does not publish a child-folder delete after its reload outlives %s',
  async (boundary) => {
    const r = await setup();
    const p = pending<api.FileBrowseResponse>();
    vi.mocked(api.deleteFileFolder).mockResolvedValue();
    vi.mocked(api.browseFiles).mockReturnValueOnce(p.promise);
    const changed = vi.fn();
    window.addEventListener('files:changed', changed);
    let done!: Promise<void>;
    act(() => {
      done = r.result.current.handleDeleteFolder({ ...folder, id: 'child' });
    });
    await waitFor(() => expect(api.browseFiles).toHaveBeenCalledTimes(2));
    if (boundary === 'unmount') r.unmount();
    else {
      h.token = 'b';
      r.rerender();
      await waitFor(() => expect(api.browseFiles).toHaveBeenCalledTimes(3));
    }
    await act(async () => {
      p.resolve({
        current_folder: folder,
        folders: [],
        files: [],
        breadcrumbs: [],
        all_folders: [],
      });
      await done;
    });
    window.removeEventListener('files:changed', changed);
    expect(changed).not.toHaveBeenCalled();
  },
);
