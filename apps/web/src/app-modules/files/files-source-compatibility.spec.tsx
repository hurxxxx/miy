import { FullscreenImageDialog as OwnedDialog } from '@miy/platform-web/media';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  AuthContext,
  type AuthContextValue,
} from '@miy/platform-web/auth-context';
import {
  FileUploadProvider as OwnedProvider,
  useFileUploadManager as ownedManager,
  FilesApiError as OwnedError,
  browseFiles as ownedBrowse,
} from '@miy/official-suite-web/files';
import {
  FileUploadProvider,
  useFileUploadManager,
} from './file-upload-provider';
import { FilesApiError, browseFiles } from './api/files-api';
import { filesModule } from './index';
import { downloadAuthenticatedContent } from '@/src/platform/browser/browser-download';
import { downloadAuthenticatedContent as ownedDownload } from '@miy/platform-web/browser';
import { formatByteSize } from '@/src/platform/format/byte-size';
import { formatByteSize as ownedFormat } from '@miy/platform-web/format';
import { FullscreenImageDialog } from '@/src/components/media/FullscreenImageDialog';
import { FeedbackProvider } from '@miy/ui';
function Consumer() {
  const manager = ownedManager();
  return <span>{manager.hasActiveUploads ? 'active' : 'idle'}</span>;
}
describe('Files source compatibility', () => {
  it('preserves single API/error/provider/helper objects behind old imports', () => {
    expect(FileUploadProvider).toBe(OwnedProvider);
    expect(useFileUploadManager).toBe(ownedManager);
    expect(filesModule.shellProviders[0]).toBe(OwnedProvider);
    expect(FilesApiError).toBe(OwnedError);
    expect(browseFiles).toBe(ownedBrowse);
    expect(downloadAuthenticatedContent).toBe(ownedDownload);
    expect(formatByteSize).toBe(ownedFormat);
    expect(FullscreenImageDialog).toBe(OwnedDialog);
  });
  it('connects legacy provider and owned consumer through the host auth/feedback contexts', () => {
    render(
      <AuthContext.Provider value={{ token: 'synthetic' } as AuthContextValue}>
        <FeedbackProvider
          labels={{
            close: 'Close',
            region: 'Notifications',
            item: 'Notification',
          }}
        >
          <FileUploadProvider>
            <Consumer />
          </FileUploadProvider>
        </FeedbackProvider>
      </AuthContext.Provider>,
    );
    expect(screen.getByText('idle')).toBeTruthy();
  });
});
