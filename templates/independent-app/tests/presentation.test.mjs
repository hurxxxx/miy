import assert from 'node:assert/strict';
import test from 'node:test';
import { applyUIContext, copyFor } from '../src/presentation.mjs';

test('the app applies its own theme and supported language without portal styles', () => {
  const document = {
    documentElement: { lang: 'ko-KR', dataset: {}, style: {} },
  };
  const locale = applyUIContext(document, { theme: 'dark', locale: 'en-US' });
  assert.equal(document.documentElement.lang, 'en-US');
  assert.equal(document.documentElement.dataset.theme, 'dark');
  assert.equal(document.documentElement.style.colorScheme, 'dark');
  assert.equal(copyFor(locale).connect, 'Connect to platform');
  assert.equal(copyFor(locale).notesTitle, 'My notes');
  const fallback = applyUIContext(document, {
    theme: 'light',
    locale: 'fr-FR',
  });
  assert.equal(fallback, 'ko-KR');
  assert.equal(copyFor(fallback).notesTitle, '내 메모');
  assert.deepEqual(
    Object.keys(copyFor('ko-KR')).sort(),
    Object.keys(copyFor('en-US')).sort(),
  );
});
