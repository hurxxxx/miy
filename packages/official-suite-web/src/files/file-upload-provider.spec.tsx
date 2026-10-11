import { act, cleanup, render, renderHook } from '@testing-library/react';
import { StrictMode, type PropsWithChildren } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  FileUploadProvider,
  useFileUploadManager,
} from './file-upload-provider';
import { uploadDriveFile, type FileItem } from './api/files-api';
const h = vi.hoisted(() => ({ token: 'a', success: vi.fn(), error: vi.fn() }));
vi.mock('@miy/platform-web/auth-context', () => ({
  useAuth: () => ({ token: h.token, user: { id: h.token } }),
}));
vi.mock('@miy/ui', async (original) => ({
  ...(await original<object>()),
  useFeedback: () => ({ success: h.success, error: h.error }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./api/files-api', () => ({ uploadDriveFile: vi.fn() }));
let start!: ReturnType<typeof useFileUploadManager>['startUpload'];
function Child() {
  start = useFileUploadManager().startUpload;
  return null;
}
function tree() {
  return (
    <FileUploadProvider>
      <Child />
    </FileUploadProvider>
  );
}
const input = () => ({
  files: [new File(['a'], 'a'), new File(['b'], 'b')],
  token: 'a',
  folderId: null,
  uploadVisibility: 'private' as const,
});
beforeEach(() => {
  h.token = 'a';
  vi.clearAllMocks();
});
afterEach(() => cleanup());
describe('Files upload session ownership', () => {
  it.each(['token', 'unmount'] as const)(
    'does not submit the next file or toast after %s',
    async (boundary) => {
      let resolve!: (v: FileItem) => void;
      vi.mocked(uploadDriveFile).mockReturnValueOnce(
        new Promise((r) => {
          resolve = r;
        }),
      );
      const r = render(tree());
      act(() => {
        expect(start(input())).toBe(true);
      });
      const signal = vi.mocked(uploadDriveFile).mock.calls[0]?.[2]?.signal;
      if (boundary === 'token') {
        h.token = 'b';
        r.rerender(tree());
      } else r.unmount();
      expect(signal?.aborted).toBe(true);
      await act(async () => {
        resolve({} as FileItem);
      });
      expect(uploadDriveFile).toHaveBeenCalledTimes(1);
      expect(h.success).not.toHaveBeenCalled();
      expect(h.error).not.toHaveBeenCalled();
    },
  );
  it('rejects a retained old-session upload callback', () => {
    const r = render(tree());
    const old = start;
    h.token = 'b';
    r.rerender(tree());
    act(() => expect(old(input())).toBe(false));
    expect(uploadDriveFile).not.toHaveBeenCalled();
  });
  it('works after StrictMode cleanup/setup with current credentials', async () => {
    vi.mocked(uploadDriveFile).mockResolvedValue({} as FileItem);
    const wrapper = ({ children }: PropsWithChildren) => (
      <StrictMode>
        <FileUploadProvider>{children}</FileUploadProvider>
      </StrictMode>
    );
    const r = renderHook(() => useFileUploadManager(), { wrapper });
    await act(async () => {
      expect(r.result.current.startUpload(input())).toBe(true);
    });
    expect(uploadDriveFile).toHaveBeenCalledTimes(2);
    expect(h.success).toHaveBeenCalledTimes(1);
  });
});
