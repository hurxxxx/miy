// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { afterEach, expect, it, vi } from 'vitest';

import {
  DateInput,
  DateTimeInput,
  resolveCalendarPickerPosition,
} from './DateInput';

afterEach(cleanup);

async function locale(language: string) {
  const value = createInstance();
  await value.init({
    lng: language,
    fallbackLng: 'en-US',
    defaultNS: 'common',
    resources: {
      'en-US': {
        common: {
          date: {
            chooseDate: 'Choose date',
            chooseDateTime: 'Choose date and time',
          },
        },
      },
      'ko-KR': {
        common: {
          date: { chooseDate: '날짜 선택', chooseDateTime: '날짜와 시간 선택' },
        },
      },
    },
  });
  return value;
}

it.each([
  ['ko-KR', 'korean', '2026년 5월 27일', '날짜 선택'],
  ['en-US', 'us', '05/27/2026', 'Choose date'],
])(
  'commits localized %s keyboard input and closes its picker with Escape',
  async (language, format, text, picker) => {
    const onValueChange = vi.fn();
    render(
      <I18nextProvider i18n={await locale(language)}>
        <DateInput
          aria-label="Start date"
          value="2026-05-26"
          dateFormat={format}
          onValueChange={onValueChange}
        />
      </I18nextProvider>,
    );
    const field = screen.getByRole('textbox', { name: 'Start date' });
    fireEvent.change(field, { target: { value: text } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onValueChange).toHaveBeenCalledWith('2026-05-27');
    fireEvent.click(screen.getByRole('button', { name: picker }));
    expect(screen.getByRole('dialog', { name: picker })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('dialog', { name: picker }), {
      key: 'Escape',
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  },
);

it('keeps invalid dates from committing and preserves the prior value', async () => {
  const onValueChange = vi.fn();
  render(
    <I18nextProvider i18n={await locale('en-US')}>
      <DateInput
        aria-label="Start date"
        dateFormat="iso"
        value="2026-02-28"
        onValueChange={onValueChange}
      />
    </I18nextProvider>,
  );
  const field = screen.getByRole('textbox', {
    name: 'Start date',
  }) as HTMLInputElement;
  fireEvent.change(field, { target: { value: '2026-02-30' } });
  fireEvent.blur(field);
  expect(onValueChange).not.toHaveBeenCalled();
  expect(field.value).toBe('2026-02-28');
});

it('keeps datetime input in local field syntax for the caller to interpret', async () => {
  const onValueChange = vi.fn();
  render(
    <I18nextProvider i18n={await locale('en-US')}>
      <DateTimeInput
        aria-label="Start time"
        dateFormat="iso"
        value="2026-03-08T01:30"
        onValueChange={onValueChange}
      />
    </I18nextProvider>,
  );
  const field = screen.getByRole('textbox', { name: 'Start time' });
  fireEvent.change(field, { target: { value: '2026-03-08 03:30' } });
  fireEvent.keyDown(field, { key: 'Enter' });
  expect(onValueChange).toHaveBeenCalledWith('2026-03-08T03:30');
});

it('keeps the existing calendar position inside a narrow viewport', () => {
  const position = resolveCalendarPickerPosition({
    anchorRect: { bottom: 600, top: 568, right: 320 },
    calendarHeight: 340,
    viewportHeight: 640,
    viewportWidth: 320,
  });
  expect(position.left).toBeGreaterThanOrEqual(8);
  expect(position.left + 288).toBeLessThanOrEqual(312);
  expect(position.top).toBeGreaterThanOrEqual(8);
  expect(position.top + 340).toBeLessThanOrEqual(568);
});
