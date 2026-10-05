import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { api } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { Instructions } from './instructions';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));
vi.mock('@pierre/diffs/react', () => ({ MultiFileDiff: () => <div /> }));

it('blocks cached-document links during a pending read and restores navigation after it completes', async () => {
  type Document = components['schemas']['DocumentOut'];
  const document = (path: string, content: string): Document => ({
    scope: 'project',
    path,
    content,
    kind: 'instructions',
    editable: true,
    exists: true,
    revision: 'saved',
  });
  const root = document(
    'AGENTS.md',
    '# Root document\n\n[Slow link](slow/AGENTS.md)\n\n[Cached link](cached/AGENTS.md)',
  );
  const cached = document('cached/AGENTS.md', '# Cached document');
  const slow = document('slow/AGENTS.md', '# Slow document');
  let finish!: (value: Document) => void;
  const pending = new Promise<Document>((resolve) => {
    finish = resolve;
  });
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/instructions')
        return {
          roots: { project: '/repo' },
          entries: [root, cached, slow].map(
            ({ scope, path, kind, editable }) => ({
              scope,
              path,
              kind,
              editable,
            }),
          ),
        };
      if (path.startsWith('/instructions/document?')) {
        const selected = new URL(
          path,
          'https://console.invalid',
        ).searchParams.get('path');
        if (selected === root.path) return root;
        if (selected === cached.path) return cached;
        if (selected === slow.path) return pending;
      }
      throw new Error('Unexpected instruction endpoint');
    });
  render(<Instructions active t={translate('en-US')} onRequest={vi.fn()} />);
  const navigation = within(
    screen.getByRole('navigation', { name: 'Agent documents' }),
  );
  fireEvent.click(await navigation.findByRole('button', { name: cached.path }));
  await screen.findByText('Cached document');
  fireEvent.click(navigation.getByRole('button', { name: root.path }));
  await screen.findByText('Root document');
  fireEvent.click(screen.getByRole('link', { name: 'Slow link' }));
  fireEvent.click(screen.getByRole('link', { name: 'Cached link' }));
  try {
    expect(screen.getByText('Root document')).toBeTruthy();
    expect(screen.queryByText('Cached document')).toBeNull();
  } finally {
    await act(async () => finish(slow));
  }
  await screen.findByText('Slow document');
  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: 'Ask Codex to edit' }),
    ).toHaveProperty('disabled', false),
  );
  fireEvent.click(navigation.getByRole('button', { name: cached.path }));
  await screen.findByText('Cached document');
  expect(
    screen.getByRole('button', { name: 'Ask Codex to edit' }),
  ).toHaveProperty('disabled', false);
  expect(
    vi
      .mocked(api)
      .mock.calls.filter(([path]) => path.includes('path=cached%2FAGENTS.md')),
  ).toHaveLength(1);
});
