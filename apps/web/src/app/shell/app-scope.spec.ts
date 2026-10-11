import { expect, it } from 'vitest';
import type { IndependentApp } from '@/src/platform/apps/independent-apps-api';
import {
  needsIndependentAppCatalog,
  scopeIndependentAppItems,
} from './app-scope';

it('does not make a builtin-only root depend on the independent-app catalog', () => {
  expect(needsIndependentAppCatalog()).toBe(true);
  expect(needsIndependentAppCatalog(['pms', 'docs'])).toBe(false);
  expect(needsIndependentAppCatalog([])).toBe(false);
  expect(needsIndependentAppCatalog(['pms', 'private-notes'])).toBe(true);
});

it('keeps the main catalog intact and applies an explicit suite scope to installed apps', () => {
  const catalog = ['personal-notes', 'another-app'].map((app_id) => ({
    definition: { definition: { app_id } },
    installations: [],
  })) as unknown as IndependentApp[];
  expect(scopeIndependentAppItems(catalog)).toBe(catalog);
  expect(scopeIndependentAppItems(catalog, ['pms', 'docs'])).toEqual([]);
  expect(scopeIndependentAppItems(catalog, ['personal-notes'])).toEqual([
    catalog[0],
  ]);
  expect(scopeIndependentAppItems(catalog, [])).toEqual([]);
});
