import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { apiFetchJson } from '@/src/platform/api/client';
import { IndependentFilePicker } from './IndependentFilePicker';
import { parseFileCandidatePage } from './independent-app-files';
import { useIndependentAppFiles } from './use-independent-app-files';
import type {
  IndependentFileSelectionRequest,
  IndependentFileSelectionResult,
} from './independent-app-host';

vi.mock('@/src/platform/api/client', async (original) => ({
  ...(await original<typeof import('@/src/platform/api/client')>()),
  apiFetchJson: vi.fn(),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const label = (key: string) => `independentApps.files.${key}`;
const source = {
  appId: 'test-app',
  installationId: 'a0000000-0000-4000-8000-000000000001',
  origin: 'https://app.example.test',
  generation: 1,
  entrypoint: '/',
};
const file = {
  file_id: 'b0000000-0000-4000-8000-000000000001',
  name: '<img src=x> report.txt',
  content_type: 'text/plain',
  size_bytes: 4,
  version: 'c'.repeat(64),
};
function request(
  id = 'd0000000-0000-4000-8000-000000000001',
): IndependentFileSelectionRequest {
  return {
    schema_version: 1,
    installation_id: source.installationId,
    audience: source.origin,
    selection_id: id,
    selection_request: 'synthetic-selection-proof',
    expires_at: new Date(Date.now() + 60000).toISOString(),
    max_bytes: 10485760,
  };
}
const context = (proof: IndependentFileSelectionRequest) => ({
  schema_version: 1,
  installation_id: proof.installation_id,
  audience: proof.audience,
  selection_id: proof.selection_id,
});
const page = (proof: IndependentFileSelectionRequest) => ({
  ...context(proof),
  items: [file],
  next_cursor: null,
  incomplete: false,
});
const selected = (proof: IndependentFileSelectionRequest) => ({
  ...context(proof),
  file,
  read_grant: 'synthetic-read-grant',
  expires_at: new Date(Date.now() + 120000).toISOString(),
});
let picker: ReturnType<typeof useIndependentAppFiles>;
const defaults = {
  token: 'synthetic-owner-login' as string | null,
  actorId: 'owner' as string | null,
  source: source as typeof source | null,
  documentVersion: 'first',
};
function Fixture(props: Partial<typeof defaults>) {
  picker = useIndependentAppFiles({ ...defaults, ...props });
  return picker.view ? (
    <IndependentFilePicker
      key={picker.view.requestId}
      picker={picker}
      appName="Synthetic app"
    />
  ) : null;
}
const view = (props: Partial<typeof defaults> = {}) => (
  <StrictMode>
    <Fixture {...props} />
  </StrictMode>
);
function start(
  proof = request(),
  signal = new AbortController().signal,
  current = () => true,
) {
  let result!: Promise<IndependentFileSelectionResult>;
  act(() => {
    result = picker.selectFile(proof, signal, current);
  });
  return result;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const calls = (suffix: string) =>
  vi.mocked(apiFetchJson).mock.calls.filter(([path]) => path.endsWith(suffix));
beforeEach(() => {
  vi.mocked(apiFetchJson).mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

it('shows only metadata and requires a separate explicit confirmation with the observed version', async () => {
  const proof = request();
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(page(proof))
    .mockResolvedValueOnce(selected(proof));
  render(view());
  expect(apiFetchJson).not.toHaveBeenCalled();
  const result = start(proof);
  await screen.findByRole('radio');
  expect(calls('candidates')).toHaveLength(1);
  expect(calls('authorize-selection')).toHaveLength(0);
  expect(screen.getByText(file.name).querySelector('img')).toBeNull();
  fireEvent.click(screen.getByRole('radio'));
  expect(calls('authorize-selection')).toHaveLength(0);
  const confirm = screen.getByRole('button', { name: label('confirm') });
  fireEvent.click(confirm);
  fireEvent.click(confirm);
  await act(async () => {
    await expect(result).resolves.toMatchObject({
      status: 'selected',
      selection: { file, read_grant: 'synthetic-read-grant' },
    });
  });
  expect(calls('authorize-selection')).toHaveLength(1);
  expect(JSON.parse(String(calls('authorize-selection')[0][2]?.body))).toEqual({
    ...context(proof),
    selection_request: proof.selection_request,
    file_id: file.file_id,
    expected_version: file.version,
  });
  expect(calls('content')).toHaveLength(0);
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
});

it('displays and selects a valid 255-code-point filename without truncating surrogate pairs', async () => {
  const proof = request();
  const unicodeFile = { ...file, name: '📄'.repeat(255) };
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce({ ...page(proof), items: [unicodeFile] })
    .mockResolvedValueOnce({ ...selected(proof), file: unicodeFile });
  render(view());
  const result = start(proof);
  await screen.findByText(unicodeFile.name);
  fireEvent.click(screen.getByRole('radio'));
  expect(calls('authorize-selection')).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: label('confirm') }));
  await act(async () => {
    await expect(result).resolves.toMatchObject({
      status: 'selected',
      selection: { file: unicodeFile },
    });
  });
  expect(calls('authorize-selection')).toHaveLength(1);
});

it('pages over empty partial results, searches explicitly and never calls an incomplete page an empty catalog', async () => {
  const proof = request();
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce({
      ...page(proof),
      items: [],
      next_cursor: 'next-page',
      incomplete: true,
    })
    .mockResolvedValueOnce(page(proof))
    .mockResolvedValueOnce(page(proof));
  render(view());
  const result = start(proof);
  await screen.findByText(label('noPageItems'));
  expect(screen.queryByText(label('empty'))).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: label('next') }));
  await screen.findByRole('radio');
  expect(JSON.parse(String(calls('candidates')[1][2]?.body)).cursor).toBe(
    'next-page',
  );
  fireEvent.change(screen.getByLabelText(label('searchLabel')), {
    target: { value: ' report ' },
  });
  expect(calls('candidates')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: label('search') }));
  await waitFor(() => expect(calls('candidates')).toHaveLength(3));
  expect(JSON.parse(String(calls('candidates')[2][2]?.body))).toMatchObject({
    cursor: null,
    query: 'report',
    limit: 25,
  });
  act(() => picker.cancel());
  await expect(result).resolves.toEqual({ status: 'canceled' });
});

it('cancels a request and rejects retained dialog actions after a new selection opens', async () => {
  const first = request();
  const second = request('d0000000-0000-4000-8000-000000000002');
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(page(first))
    .mockResolvedValueOnce(page(second));
  render(view());
  const a = start(first);
  await screen.findByRole('radio');
  const retained = picker;
  act(() => picker.cancel());
  await expect(a).resolves.toEqual({ status: 'canceled' });
  const b = start(second);
  await screen.findByRole('radio');
  act(() => {
    retained.choose(file);
    retained.cancel();
    retained.search('old');
    void retained.confirm();
  });
  expect(picker.view?.requestId).toBe(second.selection_id);
  expect(picker.view?.selected).toBeNull();
  expect(calls('candidates')).toHaveLength(2);
  expect(calls('authorize-selection')).toHaveLength(0);
  act(() => picker.cancel());
  await expect(b).resolves.toEqual({ status: 'canceled' });
});

it('does not replay an authorization after its response is lost or malformed', async () => {
  const proof = request();
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(page(proof))
    .mockRejectedValueOnce(new Error('sensitive-upstream-detail'));
  render(view());
  const result = start(proof);
  await screen.findByRole('radio');
  fireEvent.click(screen.getByRole('radio'));
  fireEvent.click(screen.getByRole('button', { name: label('confirm') }));
  await screen.findByText(label('selectionUnknown'));
  expect(screen.queryByText('sensitive-upstream-detail')).toBeNull();
  expect(
    (
      screen.getByRole('button', {
        name: label('confirm'),
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  act(() => {
    void picker.confirm();
    picker.search('again');
  });
  expect(calls('authorize-selection')).toHaveLength(1);
  expect(calls('candidates')).toHaveLength(1);
  act(() => picker.cancel());
  await expect(result).resolves.toEqual({ status: 'canceled' });
});

it.each([
  { token: 'new-owner-login' },
  { token: null, actorId: null },
  { actorId: 'other-owner' },
  { source: { ...source, generation: 2 } },
  { source: null },
  { documentVersion: 'new-document' },
])('drops late metadata on changed mounted identity: %j', async (change) => {
  const proof = request();
  const wait = deferred<unknown>();
  vi.mocked(apiFetchJson).mockReturnValueOnce(wait.promise);
  const app = render(view());
  const result = start(proof);
  const retained = picker;
  app.rerender(view(change));
  await expect(result).resolves.toEqual({ status: 'unavailable' });
  await act(async () => wait.resolve(page(proof)));
  expect(screen.queryByRole('dialog')).toBeNull();
  await expect(
    retained.selectFile(proof, new AbortController().signal, () => true),
  ).resolves.toEqual({ status: 'unavailable' });
  expect(calls('authorize-selection')).toHaveLength(0);
});

it.each(['success', 'failure'])(
  'suppresses late confirmation %s after logout',
  async (outcome) => {
    const proof = request();
    const wait = deferred<unknown>();
    vi.mocked(apiFetchJson)
      .mockResolvedValueOnce(page(proof))
      .mockReturnValueOnce(wait.promise);
    const app = render(view());
    const result = start(proof);
    await screen.findByRole('radio');
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: label('confirm') }));
    app.rerender(view({ token: null, actorId: null }));
    await expect(result).resolves.toEqual({ status: 'unavailable' });
    await act(async () => {
      if (outcome === 'success') wait.resolve(selected(proof));
      else wait.reject(new Error('old response'));
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  },
);

it('ends on channel abort and rejects concurrent requests without duplicate metadata calls', async () => {
  const proof = request();
  const controller = new AbortController();
  vi.mocked(apiFetchJson).mockResolvedValue(page(proof));
  render(view());
  const result = start(proof, controller.signal);
  await screen.findByRole('radio');
  await expect(
    picker.selectFile(proof, controller.signal, () => true),
  ).resolves.toEqual({ status: 'busy' });
  act(() => controller.abort());
  await expect(result).resolves.toEqual({ status: 'unavailable' });
  expect(calls('candidates')).toHaveLength(1);
  expect(screen.queryByRole('dialog')).toBeNull();
});

it('checks current channel synchronously before confirmation even if its close timer has not run', async () => {
  const proof = request();
  let current = true;
  vi.mocked(apiFetchJson).mockResolvedValue(page(proof));
  render(view());
  const result = start(proof, new AbortController().signal, () => current);
  await screen.findByRole('radio');
  fireEvent.click(screen.getByRole('radio'));
  current = false;
  fireEvent.click(screen.getByRole('button', { name: label('confirm') }));
  expect(calls('authorize-selection')).toHaveLength(0);
  act(() => picker.cancel());
  await expect(result).resolves.toEqual({ status: 'canceled' });
});

it('bounds unresponsive metadata and authorization, then ends at proof expiry', async () => {
  vi.useFakeTimers();
  const proof = request();
  vi.mocked(apiFetchJson).mockImplementation(
    () => new Promise(() => undefined),
  );
  render(view());
  const result = start(proof);
  await act(async () => vi.advanceTimersByTimeAsync(8001));
  expect(picker.view?.error).toBe('loadFailed');
  vi.mocked(apiFetchJson).mockResolvedValueOnce(page(proof));
  await act(async () => picker.search(''));
  act(() => picker.choose(file));
  act(() => {
    void picker.confirm();
  });
  await act(async () => vi.advanceTimersByTimeAsync(8001));
  expect(picker.view?.phase).toBe('unknown');
  expect(calls('authorize-selection')).toHaveLength(1);
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  await expect(result).resolves.toEqual({ status: 'unavailable' });
  expect(picker.view).toBeNull();
});

it.each([
  { schema_version: true },
  { installation_id: 'different' },
  { audience: 'https://other.example.test' },
  { selection_id: 'different' },
  { items: [file, file] },
  { incomplete: 'false' },
  { next_cursor: 'a\nb' },
  { extra: true },
  { items: [{ ...file, size_bytes: 10485761 }] },
  { items: [{ ...file, version: 'bad' }] },
  { items: [{ ...file, url: 'https://forbidden.test' }] },
])('rejects malformed or substituted metadata page: %j', (change) => {
  const proof = request();
  expect(() =>
    parseFileCandidatePage({ ...page(proof), ...change }, proof),
  ).toThrow('invalid-file-candidates');
});

it('never delivers a different file or object version from the confirmation response', async () => {
  const proof = request();
  vi.mocked(apiFetchJson)
    .mockResolvedValueOnce(page(proof))
    .mockResolvedValueOnce({
      ...selected(proof),
      file: { ...file, version: 'd'.repeat(64) },
    });
  render(view());
  const result = start(proof);
  await screen.findByRole('radio');
  fireEvent.click(screen.getByRole('radio'));
  fireEvent.click(screen.getByRole('button', { name: label('confirm') }));
  await screen.findByText(label('selectionUnknown'));
  act(() => picker.cancel());
  await expect(result).resolves.toEqual({ status: 'canceled' });
});
