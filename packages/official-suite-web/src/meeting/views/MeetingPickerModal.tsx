import { useAppAdmission } from '@miy/platform-web/apps';
import { useCallback, useLayoutEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { NoAccessNotice } from '@miy/platform-web/apps';
import { ResourcePickerDialog } from '@miy/platform-web/pickers';
import { useAuth } from '@miy/platform-web/auth-context';
import {
  useResourcePickerLoad,
  useResourcePickerSession,
} from '@miy/platform-web/pickers';
import {
  formatDateTime,
  normalizeTimeZone,
} from '@miy/platform-web/time/time-utils';
import { listMeetings, type MeetingListItem } from '../api/meeting-api';
import {
  INITIAL_MEETING_PICKER_STATE,
  filterMeetingsForPicker,
  meetingPickerReducer,
  sortMeetingsForPicker,
  type MeetingPickerAction,
} from './meeting-picker-model';

// listMeetings has no `q` parameter, so search remains client-side over the
// returned meeting list until the Meeting API grows a server-side search.
export interface MeetingPickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPick: (meeting: MeetingListItem) => Promise<void> | void;
  excludeMeetingIds?: string[];
}

const EMPTY_EXCLUDED_MEETING_IDS: string[] = [];

export function MeetingPickerModal(props: MeetingPickerModalProps) {
  const { token, user } = useAuth();
  const admitted = useAppAdmission('meeting');
  const scope = useRef({
    token,
    userId: user?.id,
    open: props.isOpen,
    admitted,
    epoch: 0,
  });
  if (
    scope.current.token !== token ||
    scope.current.userId !== user?.id ||
    scope.current.open !== props.isOpen ||
    scope.current.admitted !== admitted
  ) {
    scope.current = {
      token,
      userId: user?.id,
      open: props.isOpen,
      admitted,
      epoch: scope.current.epoch + 1,
    };
  }
  const epoch = scope.current.epoch;
  return props.isOpen ? (
    <MeetingPickerSession
      key={epoch}
      {...props}
      canAccess={Boolean(token) && admitted}
      isCurrent={() => scope.current.epoch === epoch}
    />
  ) : null;
}

function MeetingPickerSession({
  isOpen,
  onClose,
  onPick,
  excludeMeetingIds = EMPTY_EXCLUDED_MEETING_IDS,
  canAccess,
  isCurrent,
}: MeetingPickerModalProps & { canAccess: boolean; isCurrent: () => boolean }) {
  const { t, i18n } = useTranslation('apps');
  const { token, user } = useAuth();
  const active = useRef(false);
  useLayoutEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const timeZone = normalizeTimeZone(user?.time_zone);
  const {
    dispatch,
    handleClose,
    handlePick,
    setQuery,
    state: { error, items, loading, query, submittingId },
  } = useResourcePickerSession<MeetingListItem, MeetingPickerAction>({
    actions: {
      query: (value) => ({ type: 'query', value }),
      reset: () => ({ type: 'reset' }),
      submit: (meeting) => ({ type: 'submit', meetingId: meeting.id }),
      submitFailed: (message) => ({ type: 'submit-failed', message }),
      submitFinished: () => ({ type: 'submit-finished' }),
    },
    getPickFailedMessage: (err) =>
      err instanceof Error ? err.message : t('recording.errors.attachFailed'),
    initialState: INITIAL_MEETING_PICKER_STATE,
    onClose: () => {
      if (active.current && isCurrent()) onClose();
    },
    onPick: (item) =>
      active.current && isCurrent() && canAccess ? onPick(item) : false,
    reducer: meetingPickerReducer,
  });

  const loadMeetings = useCallback(async () => {
    if (!token) return [];
    const response = await listMeetings(token, { scope: 'all' });
    return sortMeetingsForPicker(response.items);
  }, [token]);

  useResourcePickerLoad<MeetingListItem, MeetingPickerAction>({
    actions: {
      failed: (message) => ({ type: 'failed', message }),
      load: () => ({ type: 'load' }),
      loaded: (loadedItems) => ({ type: 'loaded', items: loadedItems }),
    },
    dispatch,
    enabled: isOpen && Boolean(token) && canAccess,
    getLoadFailedMessage: (err) =>
      err instanceof Error && err.message
        ? err.message
        : t('recording.detail.meetingPicker.loadFailed'),
    loadItems: loadMeetings,
  });

  const filteredItems = useMemo(
    () =>
      filterMeetingsForPicker(items, {
        excludeMeetingIds,
        query,
      }),
    [excludeMeetingIds, items, query],
  );

  return (
    <ResourcePickerDialog
      accessNotice={
        <NoAccessNotice
          appLabel={t('recording.title')}
          action={t('recording.detail.addMeeting')}
        />
      }
      canAccess={canAccess}
      closeLabel={t('common:actions.close')}
      description={t('recording.detail.meetingPicker.description')}
      emptyLabel={t('recording.detail.meetingPicker.empty')}
      error={error}
      getItemId={(item) => item.id}
      isOpen={isOpen}
      items={filteredItems}
      loading={loading}
      onClose={handleClose}
      onPick={(item) => void handlePick(item)}
      renderItem={(item) => (
        <div className="min-w-0">
          <p className="app-text-body line-clamp-1 text-app-ink">
            {item.title || t('recording.untitled')}
          </p>
          <p className="app-text-caption text-app-ink/40">
            {formatDateTime(item.start_at, {
              day: 'numeric',
              hour: '2-digit',
              locale: i18n.language,
              minute: '2-digit',
              month: 'short',
              timeZone,
            })}
            {item.organizer_name ? ` · ${item.organizer_name}` : ''}
          </p>
        </div>
      )}
      search={{
        label: t('common:actions.search'),
        onChange: setQuery,
        placeholder: t('recording.detail.meetingPicker.searchPlaceholder'),
        value: query,
      }}
      submittingId={submittingId}
      title={t('recording.detail.meetingPicker.title')}
    />
  );
}
