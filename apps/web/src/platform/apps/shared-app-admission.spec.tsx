import * as shared from '@miy/platform-web/apps';
import * as picker from '@miy/platform-web/pickers';
import * as meeting from '@miy/official-suite-web/meeting';
import * as meetingApi from '@miy/official-suite-web/meeting/api/meeting-api';
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
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  createAppsBootstrap,
  createAuthUser,
  createBootstrapApp,
} from '../../../tests/fixtures/company';
import { i18n } from '../i18n';
import * as legacy from './app-bootstrap-context';
import * as legacyApi from '../../app-modules/meeting/public-api';
import { ResourcePickerDialog } from '../../components/picker/ResourcePickerDialog';
import { NoAccessNotice } from '../../components/common/NoAccessNotice';
import { useResourcePickerSession } from '../pickers/resource-picker-session';
import { projectPickerItems } from '../pickers/picker-model';

const fetcher = vi.fn<typeof fetch>();
const row: meeting.MeetingListItem = {
  id: 'meeting-one',
  title: 'Shared meeting',
  organizer_id: 'owner',
  organizer_name: 'Owner',
  start_at: '2026-10-07T10:00:00',
  end_at: '2026-10-07T11:00:00',
  status: 'scheduled',
  attendee_count: 1,
  task_link_count: 0,
  doc_link_count: 0,
};
beforeEach(async () => {
  await i18n.changeLanguage('en-US');
  vi.stubGlobal('fetch', fetcher);
  fetcher.mockReset().mockImplementation(
    async () =>
      new Response(JSON.stringify({ items: [row], total: 1 }), {
        headers: { 'Content-Type': 'application/json' },
      }),
  );
});
afterEach(async () => {
  cleanup();
  vi.unstubAllGlobals();
  await i18n.changeLanguage('ko-KR');
});

it('keeps legacy API errors/functions, admission Provider and shared picker objects identical', () => {
  for (const [name, value] of Object.entries(meetingApi))
    expect(Reflect.get(legacyApi, name)).toBe(value);
  expect(legacy.AppBootstrapProvider).toBe(shared.AppBootstrapProvider);
  expect(legacy.useAppAdmission).toBe(shared.useAppAdmission);
  expect(ResourcePickerDialog).toBe(picker.ResourcePickerDialog);
  expect(NoAccessNotice).toBe(shared.NoAccessNotice);
  expect(useResourcePickerSession).toBe(picker.useResourcePickerSession);
  expect(projectPickerItems).toBe(picker.projectPickerItems);
});

function Probe() {
  const old = legacy.useAppBootstrapContext();
  const current = shared.useAppBootstrapContext();
  return (
    <output>
      {old === current && shared.useAppAdmission('meeting')
        ? 'shared admitted'
        : 'shared denied'}
    </output>
  );
}
function view(admitted: boolean, onPick = vi.fn(), onClose = vi.fn()) {
  const data = createAppsBootstrap({
    apps: [{ ...createBootstrapApp('meeting'), enabled: admitted }],
  });
  return (
    <StrictMode>
      <AuthContext.Provider
        value={
          {
            token: 'synthetic-session',
            user: createAuthUser({ time_zone: 'UTC' }),
          } as AuthContextValue
        }
      >
        <legacy.AppBootstrapProvider
          value={{ data, loading: false, error: null, reload: () => undefined }}
        >
          <Probe />
          <meeting.MeetingPickerModal
            isOpen
            onPick={onPick}
            onClose={onClose}
          />
        </legacy.AppBootstrapProvider>
      </AuthContext.Provider>
    </StrictMode>
  );
}
it('the old shell Provider supplies live admission to the actual new picker without another fetcher/context', async () => {
  const mounted = render(view(false));
  expect(screen.getByText('shared denied')).toBeTruthy();
  expect(fetcher).not.toHaveBeenCalled();
  mounted.rerender(view(true));
  await screen.findByText(row.title);
  expect(screen.getByText('shared admitted')).toBeTruthy();
  expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/meeting/meetings?scope=all',
    expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer synthetic-session',
        'X-MIY-Locale': 'en-US',
      }),
    }),
  );
  mounted.rerender(view(false));
  expect(screen.queryByText(row.title)).toBeNull();
});
it('preserves Recording-style void selection: close is not an attachment completion receipt', async () => {
  let complete!: () => void;
  const attachment = new Promise<void>((resolve) => {
    complete = resolve;
  });
  const attach = vi.fn<(id: string) => Promise<void>>(() => attachment);
  const onPick = vi.fn((selected: meeting.MeetingListItem) => {
    void attach(selected.id);
  });
  const onClose = vi.fn();
  render(view(true, onPick, onClose));
  await screen.findByText(row.title);
  await act(async () =>
    fireEvent.click(screen.getByRole('button', { name: /Shared meeting/ })),
  );
  expect(attach).toHaveBeenCalledExactlyOnceWith(row.id);
  expect(onClose).toHaveBeenCalledOnce();
  await act(async () => complete());
  expect(onClose).toHaveBeenCalledOnce();
});
