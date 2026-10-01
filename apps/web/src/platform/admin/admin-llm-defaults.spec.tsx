import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AdminLlmDefaults } from './admin-llm-defaults';
import {
  updateAdminAiModelDefault,
  type AdminAiModelSettings,
} from './admin-ai-model-settings-api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('./admin-ai-model-settings-api', () => ({
  updateAdminAiModelDefault: vi.fn(),
}));
vi.mock('@miy/ui', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@miy/ui')>()),
  useFeedback: () => ({ success: vi.fn(), error: vi.fn() }),
}));

function snapshot(defaultModel: string, version: number): AdminAiModelSettings {
  return {
    registry_digest: 'registry',
    provider_kinds: ['openrouter'],
    workloads: [],
    orphaned_overrides: [],
    providers: [
      {
        provider_id: 'conn_main',
        provider_kind: 'openrouter',
        display_name: 'Main',
        route_mode: 'external',
        credential_kind: 'api_key',
        enabled: true,
        endpoint_url: 'https://openrouter.ai/api/v1',
        endpoint_source: 'custom',
        has_api_key: true,
        default_model_id: defaultModel,
        version,
        updated_at: null,
        preset: '',
        verified: false,
      },
    ],
    models: ['model-a', 'model-b'].map((id) => ({
      id,
      provider_id: 'conn_main',
      model_key: id,
      display_name: id,
      capabilities: ['chat', 'tool_calling'],
      enabled: true,
      source: 'manual',
      discovery_status: 'active',
      last_seen_at: null,
      version: 1,
      updated_at: null,
    })),
    defaults: [
      {
        model_family: 'generation',
        app_id: '',
        route_mode: 'external',
        provider_id: 'conn_main',
        model_id: null,
        max_output_tokens: null,
        version: 1,
      },
    ],
  };
}

describe('LLM defaults refresh', () => {
  it('uses the refreshed connection model when saving an unrelated output cap', async () => {
    const onSaved = vi.fn();
    const view = render(
      <AdminLlmDefaults
        token="test"
        data={snapshot('model-a', 1)}
        disabled={false}
        onSave={async (_key, mutation) => {
          onSaved(await mutation());
        }}
      />,
    );
    const refreshed = snapshot('model-b', 2);
    vi.mocked(updateAdminAiModelDefault).mockResolvedValue(refreshed);
    view.rerender(
      <AdminLlmDefaults
        token="test"
        data={refreshed}
        disabled={false}
        onSave={async (_key, mutation) => {
          onSaved(await mutation());
        }}
      />,
    );
    const form = screen.getByRole('form', {
      name: 'admin.console.aiSecurity.modelSettings.routes.external',
    });
    const model = within(form).getByRole('combobox', {
      name: 'admin.console.aiSecurity.modelSettings.providers.defaultModel',
    });
    expect((model as HTMLSelectElement).value).toBe('model-b');
    fireEvent.change(within(form).getByRole('spinbutton'), {
      target: { value: '8' },
    });
    fireEvent.submit(form);
    await waitFor(() =>
      expect(updateAdminAiModelDefault).toHaveBeenCalledWith(
        'test',
        '',
        'external',
        {
          model_family: 'generation',
          expected_registry_digest: 'registry',
          expected_version: 1,
          expected_provider_version: 2,
          provider_id: 'conn_main',
          model_id: 'model-b',
          max_output_tokens: 8192,
        },
      ),
    );
    expect(onSaved).toHaveBeenCalledWith(refreshed);
  });
});

it('separates decision defaults and hides generation caps and models', async () => {
  const data = snapshot('model-a', 1);
  data.models.push({
    ...data.models[0],
    id: 'decision',
    model_key: 'decision',
    display_name: 'Decision',
    capabilities: ['decision'],
  });
  data.defaults.push({
    model_family: 'decision',
    app_id: '',
    route_mode: 'external',
    provider_id: 'conn_main',
    model_id: 'decision',
    max_output_tokens: null,
    version: 2,
  });
  render(
    <AdminLlmDefaults
      token="test"
      data={data}
      disabled={false}
      onSave={async (_key, mutation) => {
        await mutation();
      }}
    />,
  );
  fireEvent.change(
    screen.getByRole('combobox', {
      name: 'admin.console.aiSecurity.llmDefaults.family',
    }),
    { target: { value: 'decision' } },
  );
  const form = screen.getByRole('form', {
    name: 'admin.console.aiSecurity.modelSettings.routes.external',
  });
  expect(within(form).queryByRole('spinbutton')).toBeNull();
  expect(
    within(form).queryByRole('option', { name: 'model-a · model-a' }),
  ).toBeNull();
  expect(
    within(form).getByRole('option', { name: 'Decision · decision' }),
  ).toBeTruthy();
  fireEvent.submit(form);
  await waitFor(() =>
    expect(updateAdminAiModelDefault).toHaveBeenLastCalledWith(
      'test',
      '',
      'external',
      expect.objectContaining({
        model_family: 'decision',
        model_id: 'decision',
        max_output_tokens: null,
        expected_version: 2,
      }),
    ),
  );
});
