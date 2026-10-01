import { act, fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { api } from './api';
import type { components } from './api.generated';
import { translate } from './i18n';
import { Templates } from './templates';

vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: vi.fn(),
}));

type Template = components['schemas']['TemplateOut'];
const archived: Template = {
  id: '11111111-1111-4111-8111-111111111111',
  version: 2,
  archived: true,
  updated_at: '2026-10-01T00:00:00Z',
  definition: {
    name: 'Archived work',
    description: '',
    directory: '.',
    context: '',
    references: [],
    skills: [],
    prompt: 'Review the repository',
    variables: [],
    stage: 'plan',
    permissions: 'ask',
    isolate: false,
    shared_resources: true,
    model: null,
    effort: null,
  },
};

it.each([false, true])(
  'keeps the current archived filter when an older list settles (reject=%s)',
  async (reject) => {
    let resolveOld!: (rows: Template[]) => void;
    let rejectOld!: (reason: Error) => void;
    const older = new Promise<Template[]>((resolve, reject) => {
      resolveOld = resolve;
      rejectOld = reject;
    });
    vi.mocked(api)
      .mockReset()
      .mockReturnValueOnce(older)
      .mockResolvedValueOnce([archived]);
    const onError = vi.fn();
    render(
      <Templates
        t={translate('en-US')}
        openTask={vi.fn()}
        openHistory={vi.fn()}
        onError={onError}
      />,
    );
    fireEvent.click(screen.getByLabelText('Show archived templates'));
    await screen.findByRole('heading', { name: 'Archived work' });
    await act(async () => {
      if (reject) rejectOld(new Error('older request failed'));
      else resolveOld([]);
    });
    expect(screen.getByRole('heading', { name: 'Archived work' })).toBeTruthy();
    expect(
      (screen.getByLabelText('Show archived templates') as HTMLInputElement)
        .checked,
    ).toBe(true);
    expect(onError).not.toHaveBeenCalled();
  },
);
