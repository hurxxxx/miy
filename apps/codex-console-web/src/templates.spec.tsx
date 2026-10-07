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

it('identifies a removed selected skill and preserves it until the owner edits it', async () => {
  const row: Template = {
    ...archived,
    archived: false,
    definition: {
      ...archived.definition,
      name: 'Custom review',
      skills: ['retired-review'],
    },
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path.startsWith('/templates/catalog'))
        return { skills: [], models: [], workspace: '/project' };
      return [row];
    });
  render(
    <Templates
      t={translate('en-US')}
      openTask={vi.fn()}
      openHistory={vi.fn()}
      onError={vi.fn()}
    />,
  );
  await screen.findByRole('heading', { name: 'Custom review' });
  fireEvent.keyDown(screen.getByRole('button', { name: 'Template actions' }), {
    key: 'ArrowDown',
  });
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Edit' }));
  await screen.findByText(
    '— Unavailable skill; remove or replace it before running.',
  );
  const skill = screen.getByRole('checkbox', {
    name: /retired-review/,
  }) as HTMLInputElement;
  expect(skill.checked).toBe(true);
  fireEvent.click(skill);
  fireEvent.click(screen.getByRole('button', { name: 'Save template' }));
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/templates/${row.id}`,
      expect.objectContaining({
        definition: expect.objectContaining({
          skills: [],
          prompt: row.definition.prompt,
        }),
      }),
      'PUT',
    ),
  );
});

it('saves the selected app and loads native capabilities for its own directory', async () => {
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/workbench/catalog')
        return {
          items: [
            {
              app_id: 'review-app',
              title: 'Review app',
              source_status: 'ready',
            },
            {
              app_id: 'missing-app',
              title: 'Missing source',
              source_status: 'unconfigured',
            },
            {
              app_id: 'missing-executor',
              title: 'Source without executor',
              source_status: 'ready',
              discovery: 'source',
              execution_status: 'unconfigured',
            },
          ],
        };
      if (path.startsWith('/templates/catalog'))
        return { skills: [], models: [], workspace: '/apps/review' };
      return [];
    });
  render(
    <Templates
      t={translate('en-US')}
      openTask={vi.fn()}
      openHistory={vi.fn()}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'Create template' }),
  );
  await screen.findByRole('option', { name: 'Review app · review-app' });
  expect(
    (
      screen.getByRole('option', {
        name: 'Missing source · missing-app',
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole('option', {
        name: 'Source without executor · missing-executor',
      }) as HTMLOptionElement
    ).disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText('Template name'), {
    target: { value: 'App checks' },
  });
  fireEvent.change(screen.getByLabelText('Prompt'), {
    target: { value: 'Run the app checks' },
  });
  fireEvent.change(screen.getByLabelText('Application source'), {
    target: { value: 'review-app' },
  });
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/templates/catalog?directory_name=.&app_id=review-app',
      undefined,
      'GET',
      expect.any(AbortSignal),
    ),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save template' }));
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      '/templates',
      expect.objectContaining({ app_id: 'review-app' }),
    ),
  );
});

it('requires a configured development installation for delivery templates', async () => {
  const id = '61fdd4e5-f54e-4eeb-a62f-7f76bdff38ee';
  const row: Template = {
    ...archived,
    archived: false,
    definition: {
      ...archived.definition,
      name: 'App preview',
      app_id: 'review-app',
      purpose: 'deployment',
    },
  };
  vi.mocked(api)
    .mockReset()
    .mockImplementation(async (path) => {
      if (path === '/workbench/catalog')
        return {
          items: [
            {
              app_id: 'review-app',
              title: 'Review app',
              source_status: 'ready',
            },
          ],
        };
      if (path.endsWith('/installations'))
        return {
          state: 'ready',
          items: [
            {
              id,
              environment: 'development',
              origin: 'https://preview.example.test',
              delivery_configured: true,
            },
            {
              id: 'd2bcd74c-426a-4768-a5ca-0ce3b08843fe',
              environment: 'production',
              origin: 'https://production.example.test',
              delivery_configured: true,
            },
          ],
        };
      if (path.startsWith('/templates/catalog'))
        return { skills: [], models: [], workspace: '/apps/review' };
      return [row];
    });
  render(
    <Templates
      t={translate('en-US')}
      openTask={vi.fn()}
      openHistory={vi.fn()}
      onError={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole('button', { name: 'Select an installation' }),
  );
  await screen.findByRole('option', {
    name: `https://preview.example.test · ${id}`,
  });
  expect(
    screen.queryByRole('option', { name: /https:\/\/production/ }),
  ).toBeNull();
  fireEvent.change(screen.getByLabelText('Development installation'), {
    target: { value: id },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save template' }));
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      `/templates/${row.id}`,
      expect.objectContaining({
        definition: expect.objectContaining({
          app_id: 'review-app',
          purpose: 'deployment',
          installation_id: id,
        }),
      }),
      'PUT',
    ),
  );
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path.endsWith('/run')),
  ).toBe(false);
});
