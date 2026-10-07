import { cleanup } from '@testing-library/react';
import { afterEach as cleanupAfterEach } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getDocsCollabSession,
  saveDocsCollabSnapshot,
  type DocsCollabSession,
  type DocsPageItem,
} from '../api/docs-api';
import { DocsBlockContentSurface } from './DocsBlockContentSurface';

interface MockEditorProps {
  sessionKey: string;
  loadSession: () => Promise<{ user: { id: string } }>;
  onChange: (
    blocks: Record<string, unknown>[],
    metadata: { yjsState: string },
  ) => void;
}

const editors = vi.hoisted(() => ({ instances: [] as MockEditorProps[] }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../api/docs-api', () => ({
  makeDocsPageRef: (type: string, id: string) => `${type}__${id}`,
  getDocsCollabSession: vi.fn(),
  saveDocsCollabSnapshot: vi.fn(),
}));
vi.mock('@miy/ui', () => ({
  BlockViewer: () => <div>Read document</div>,
  BlockEditor: () => <div>Edit document</div>,
  CollaborativeBlockEditor: (props: MockEditorProps) => {
    useState(() => {
      editors.instances.push(props);
      return null;
    });
    return (
      <button
        onClick={() =>
          props.onChange([{ text: 'Local edit' }], { yjsState: 'yjs-edit' })
        }
      >
        Edit together
      </button>
    );
  },
}));

function page(id = 'page-1'): DocsPageItem {
  return {
    id,
    doc_id: 'doc-1',
    source_type: 'native_doc_page',
    source_page_id: id,
    title: 'Page',
    parent_id: null,
    sort_order: 1000,
    content_format: 'block',
    content_blocks: [],
    content_text: null,
    can_edit: true,
    realtime_collab: true,
    created_by_id: 'owner',
    created_by_name: 'Owner',
    trashed_at: null,
    created_at: '2026-10-06T00:00:00Z',
    updated_at: '2026-10-06T00:00:00Z',
  };
}

const snapshot = {
  updated_at: '2026-10-06T00:00:00Z',
  last_snapshot_at: '2026-10-06T00:00:00Z',
};
const callbacks = {
  onStandaloneBlocksChange: vi.fn(),
  onCollaborativeBlocksChange: vi.fn(),
};

function edit() {
  fireEvent.click(
    screen.getByRole('button', { name: 'apps:docs.startEditing' }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Edit together' }));
}

describe('Docs collaboration save feedback', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    editors.instances = [];
    callbacks.onCollaborativeBlocksChange.mockClear();
    vi.mocked(getDocsCollabSession).mockReset();
    vi.mocked(saveDocsCollabSnapshot).mockReset().mockResolvedValue(snapshot);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows a failed save and retries the retained edit without changing editor content', async () => {
    vi.mocked(saveDocsCollabSnapshot).mockRejectedValueOnce(
      new Error('writer unavailable'),
    );
    render(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-1"
        {...callbacks}
      />,
    );
    edit();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(screen.getByRole('alert').textContent).toContain(
      'apps:docs.collab.saveFailed',
    );
    expect(screen.getByRole('button', { name: 'Edit together' })).toBeTruthy();
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'apps:docs.collab.retrySave' }),
      );
    });
    expect(screen.queryByRole('alert')).toBeNull();
    expect(saveDocsCollabSnapshot).toHaveBeenCalledTimes(2);
    expect(saveDocsCollabSnapshot).toHaveBeenLastCalledWith(
      'token-1',
      'native_doc_page__page-1',
      {
        content_blocks: [{ text: 'Local edit' }],
        yjs_state: 'yjs-edit',
      },
    );
  });

  it('keeps the failure visible if the same page becomes read-only', async () => {
    vi.mocked(saveDocsCollabSnapshot).mockRejectedValue(new Error('forbidden'));
    const { rerender } = render(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-1"
        {...callbacks}
      />,
    );
    edit();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    rerender(
      <DocsBlockContentSurface
        page={page()}
        canEdit={false}
        token="token-1"
        {...callbacks}
      />,
    );
    expect(screen.getByRole('alert').textContent).toContain(
      'apps:docs.collab.saveFailed',
    );
    expect(screen.getByText('Read document')).toBeTruthy();
  });

  it('flushes the previous page under its own reference before editing the next page', async () => {
    const { rerender } = render(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-1"
        {...callbacks}
      />,
    );
    edit();
    await act(async () => {
      rerender(
        <DocsBlockContentSurface
          page={page('page-2')}
          canEdit
          token="token-1"
          {...callbacks}
        />,
      );
    });
    expect(saveDocsCollabSnapshot).toHaveBeenNthCalledWith(
      1,
      'token-1',
      'native_doc_page__page-1',
      {
        content_blocks: [{ text: 'Local edit' }],
        yjs_state: 'yjs-edit',
      },
    );
    edit();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(saveDocsCollabSnapshot).toHaveBeenNthCalledWith(
      2,
      'token-1',
      'native_doc_page__page-2',
      {
        content_blocks: [{ text: 'Local edit' }],
        yjs_state: 'yjs-edit',
      },
    );
  });

  it('remounts the editor on login change and ignores an old editor change callback', async () => {
    const { rerender } = render(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-1"
        {...callbacks}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'apps:docs.startEditing' }),
    );
    const oldEditor = editors.instances[0];
    rerender(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-2"
        {...callbacks}
      />,
    );
    expect(editors.instances).toHaveLength(2);
    expect(editors.instances[1].sessionKey).not.toBe(oldEditor.sessionKey);
    expect(editors.instances[1].sessionKey).not.toContain('token-2');
    act(() =>
      oldEditor.onChange([{ text: 'Stale edit' }], { yjsState: 'stale' }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(saveDocsCollabSnapshot).not.toHaveBeenCalled();
    expect(callbacks.onCollaborativeBlocksChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Edit together' }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    expect(saveDocsCollabSnapshot).toHaveBeenCalledExactlyOnceWith(
      'token-2',
      'native_doc_page__page-1',
      {
        content_blocks: [{ text: 'Local edit' }],
        yjs_state: 'yjs-edit',
      },
    );
  });

  it('rejects an old login session response and loads the new editor with the new identity', async () => {
    let completeOld!: (session: DocsCollabSession) => void;
    const session: DocsCollabSession = {
      page_ref: 'native_doc_page__page-1',
      source_type: 'native_doc_page',
      source_page_id: 'page-1',
      can_edit: true,
      room_key: 'page-1',
      ws_path: '/collab',
      user: { id: 'new-user', full_name: 'New user' },
      realtime_status: 'enabled',
      read_only_reason: null,
      snapshot_content_blocks: [],
      yjs_state: null,
    };
    vi.mocked(getDocsCollabSession)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            completeOld = resolve;
          }),
      )
      .mockResolvedValueOnce(session);
    const { rerender } = render(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-1"
        {...callbacks}
      />,
    );
    fireEvent.click(
      screen.getByRole('button', { name: 'apps:docs.startEditing' }),
    );
    const oldLoad = editors.instances[0].loadSession();
    const oldRejected = expect(oldLoad).rejects.toThrow(
      'apps:docs.collab.startFailed',
    );
    rerender(
      <DocsBlockContentSurface
        page={page()}
        canEdit
        token="token-2"
        {...callbacks}
      />,
    );
    expect(editors.instances).toHaveLength(2);
    await expect(editors.instances[1].loadSession()).resolves.toEqual(
      expect.objectContaining({
        user: { id: 'new-user', fullName: 'New user' },
      }),
    );
    completeOld({
      ...session,
      user: { id: 'old-user', full_name: 'Old user' },
    });
    await oldRejected;
    expect(getDocsCollabSession).toHaveBeenNthCalledWith(
      1,
      'token-1',
      'native_doc_page__page-1',
    );
    expect(getDocsCollabSession).toHaveBeenNthCalledWith(
      2,
      'token-2',
      'native_doc_page__page-1',
    );
    expect(saveDocsCollabSnapshot).not.toHaveBeenCalled();
  });
});

cleanupAfterEach(cleanup);
