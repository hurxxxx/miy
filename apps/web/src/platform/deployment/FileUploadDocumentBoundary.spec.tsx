import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from '@testing-library/react';
import {
  FileUploadProvider,
  useFileUploadManager,
} from '@miy/official-suite-web/files';
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { FirstPartyDocumentBoundary } from './FirstPartyDocumentBoundary';
import {
  installFirstPartyNavigation,
  reloadFirstPartyDocument,
} from './first-party-navigation';

const feedback = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('@miy/platform-web/auth-context', () => ({
  useAuth: () => ({ token: 'synthetic-upload-token' }),
}));
vi.mock('@miy/ui', async (original) => ({
  ...(await original<object>()),
  useFeedback: () => feedback,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./first-party-navigation', async (original) => ({
  ...(await original<typeof import('./first-party-navigation')>()),
  reloadFirstPartyDocument: vi.fn(),
}));

// Exercise the real upload adapter/batch with a controlled slow XHR. No fetch,
// service, files, credentials or browser storage from another user are used.
class SlowUpload {
  static requests: SlowUpload[] = [];
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 200;
  responseText = '{}';
  abort = vi.fn(() => this.onabort?.());
  open(method: string, path: string) {
    expect([method, path]).toEqual(['POST', '/api/v1/files/upload']);
  }
  setRequestHeader() {}
  send() {
    SlowUpload.requests.push(this);
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.(
      new ProgressEvent('progress', { lengthComputable: true, loaded, total }),
    );
  }
  finish(fail = false) {
    if (fail) this.onerror?.();
    else this.onload?.();
  }
}

const target = '/apps/home?from=files#content';
const handoff = { selected: 'synthetic-navigation-state' };
const nativeWindow = window;
let removeNavigation = () => {};
let assign: ReturnType<typeof vi.fn>;

function UploadScreen() {
  const manager = useFileUploadManager();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <input aria-label="Old Files input" defaultValue="Retained Files input" />
      <output aria-label="Owned location">{location.pathname}</output>
      <button
        onClick={() =>
          manager.startUpload({
            files: [new File(['aaaa'], 'a.txt'), new File(['bbbb'], 'b.txt')],
            folderId: null,
            token: 'synthetic-upload-token',
            uploadVisibility: 'private',
          })
        }
      >
        Upload
      </button>
      <a href={target}>Link to Home</a>
      <button onClick={() => navigate(target, { state: handoff })}>
        Programmatic Home
      </button>
    </>
  );
}

function unloadIsProtected() {
  const event = new Event('beforeunload', { cancelable: true });
  nativeWindow.dispatchEvent(event);
  return event.defaultPrevented;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  SlowUpload.requests = [];
  nativeWindow.history.replaceState(null, '', '/apps/files');
  assign = vi.fn();
  const location = new Proxy({} as Location, {
    get: (_object, key) =>
      key === 'assign'
        ? assign
        : Reflect.get(nativeWindow.location, key, nativeWindow.location),
  });
  const runtime: Window = new Proxy(nativeWindow, {
    get(object, key) {
      if (key === 'location') return location;
      if (key === 'parent') return runtime;
      const value = Reflect.get(object, key, object);
      if (
        [
          'setTimeout',
          'clearTimeout',
          'addEventListener',
          'removeEventListener',
          'dispatchEvent',
        ].includes(String(key))
      )
        return value.bind(object);
      return value;
    },
  });
  vi.stubGlobal('window', runtime);
  vi.stubGlobal('XMLHttpRequest', SlowUpload);
  removeNavigation = installFirstPartyNavigation('official');
});

afterEach(() => {
  removeNavigation();
  cleanup();
  vi.unstubAllGlobals();
  nativeWindow.history.replaceState(null, '', '/');
  vi.useRealTimers();
});

it.each(['link', 'programmatic'] as const)(
  'keeps slow queued uploads and old UI alive for %s navigation until the whole batch ends',
  async (navigation) => {
    render(
      <BrowserRouter>
        <FirstPartyDocumentBoundary owner="official">
          <FileUploadProvider>
            <UploadScreen />
          </FileUploadProvider>
        </FirstPartyDocumentBoundary>
      </BrowserRouter>,
    );
    expect(unloadIsProtected()).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    expect(SlowUpload.requests).toHaveLength(1);
    const first = SlowUpload.requests[0];
    act(() => first.progress(2, 4));
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe(
      '25',
    );
    expect(unloadIsProtected()).toBe(true);
    fireEvent.click(
      screen.getByRole(navigation === 'link' ? 'link' : 'button', {
        name: navigation === 'link' ? 'Link to Home' : 'Programmatic Home',
      }),
    );
    await act(async () => vi.advanceTimersByTime(300));
    expect(assign).not.toHaveBeenCalled();
    expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue('Retained Files input')).toBeTruthy();
    expect(screen.getByLabelText('Owned location').textContent).toBe(
      '/apps/files',
    );
    expect(first.abort).not.toHaveBeenCalled();
    await act(async () => first.finish());
    expect(SlowUpload.requests).toHaveLength(2);
    const second = SlowUpload.requests[1];
    await act(async () => vi.advanceTimersByTime(200));
    expect(unloadIsProtected()).toBe(true);
    expect(assign).not.toHaveBeenCalled();
    expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    expect(second.abort).not.toHaveBeenCalled();
    await act(async () => second.finish());
    await act(async () => vi.advanceTimersByTime(100));
    expect(feedback.success).toHaveBeenCalledOnce();
    expect(unloadIsProtected()).toBe(false);
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe(
      '100',
    );
    if (navigation === 'link') {
      expect(assign).toHaveBeenCalledExactlyOnceWith(target);
      expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    } else {
      expect(reloadFirstPartyDocument).toHaveBeenCalledOnce();
      expect(nativeWindow.history.state.usr).toEqual(handoff);
      expect(assign).not.toHaveBeenCalled();
    }
    expect(first.abort).not.toHaveBeenCalled();
    expect(second.abort).not.toHaveBeenCalled();
  },
);

it.each(['link', 'programmatic'] as const)(
  'releases %s navigation and native unload protection after an upload failure',
  async (navigation) => {
    render(
      <BrowserRouter>
        <FirstPartyDocumentBoundary owner="official">
          <FileUploadProvider>
            <UploadScreen />
          </FileUploadProvider>
        </FirstPartyDocumentBoundary>
      </BrowserRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    fireEvent.click(
      screen.getByRole(navigation === 'link' ? 'link' : 'button', {
        name: navigation === 'link' ? 'Link to Home' : 'Programmatic Home',
      }),
    );
    await act(async () => vi.advanceTimersByTime(300));
    expect(assign).not.toHaveBeenCalled();
    expect(reloadFirstPartyDocument).not.toHaveBeenCalled();
    await act(async () => SlowUpload.requests[0].finish(true));
    await act(async () => vi.advanceTimersByTime(100));
    expect(SlowUpload.requests).toHaveLength(1);
    expect(feedback.error).toHaveBeenCalledOnce();
    expect(unloadIsProtected()).toBe(false);
    expect(
      navigation === 'link' ? assign : reloadFirstPartyDocument,
    ).toHaveBeenCalledOnce();
    expect(screen.getByDisplayValue('Retained Files input')).toBeTruthy();
  },
);
