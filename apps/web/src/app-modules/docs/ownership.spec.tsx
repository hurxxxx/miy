import { expect, it, vi } from 'vitest';
import * as docs from '@miy/official-suite-web/docs';
import * as oldPublic from './public-api';
import * as oldApi from './api/docs-api';
import * as oldPickerModel from './api/docs-hub-picker-model';
import * as oldReorder from './api/docs-page-reorder';
import { docsModule } from '@miy/official-suite-web/docs/module';
import { docsModule as oldModule } from './index';
import { DocsApiError } from '@miy/official-suite-web/docs';
import { apiFetchJsonWithMappedError } from '@miy/platform-web/api-client';
import { apiFetchJsonWithMappedError as oldClient } from '@/src/platform/api/client';
import { docsMessages } from '@miy/official-suite-web/docs/messages';
import { resources } from '@/src/platform/i18n/resources';

// Public cross-app consumers must not eagerly evaluate either viewer or picker.
vi.mock('@miy/official-suite-web/docs/views/DocsViewerModal', () => {
  throw new Error('eager Docs viewer');
});
vi.mock('@miy/official-suite-web/docs/views/DocsHubPickerModal', () => {
  throw new Error('eager Docs picker');
});

it('retains the same public functions, lazy viewers, picker and API error identity', () => {
  for (const old of [oldPublic, oldApi, oldPickerModel, oldReorder])
    for (const [name, value] of Object.entries(old))
      expect((docs as Record<string, unknown>)[name]).toBe(value);
  expect(Object.keys(oldPublic).sort()).toEqual(Object.keys(docs).sort());
  expect(new oldApi.DocsApiError(403, 'synthetic')).toBeInstanceOf(
    DocsApiError,
  );
  expect(oldClient).toBe(apiFetchJsonWithMappedError);
  expect(oldModule).toBe(docsModule);
});

it('composes the exact owned Docs catalogs without loading a business screen', () => {
  for (const locale of ['ko-KR', 'en-US'] as const)
    expect(resources[locale].apps.docs).toBe(docsMessages[locale]);
});
