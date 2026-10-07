import { render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';

import { pmsHelpGuideRegistration } from '../app-modules/pms';
import AppRoot from './AppRoot';
import { AppContent } from './shell/AppContent';

vi.mock('./shell/AppContent', () => ({ AppContent: vi.fn(() => null) }));

it('selects PMS help explicitly for both legacy shell routes and the help modal', () => {
  render(<AppRoot />);
  const props = vi.mocked(AppContent).mock.calls[0][0];
  expect(props.helpGuides).toEqual([pmsHelpGuideRegistration]);
  expect(
    props.helpRoutes?.find((route) => route.path === '/help')?.element,
  ).toMatchObject({ props: { guides: props.helpGuides } });
  expect(
    props.helpRoutes?.find((route) => route.path === '/help/pms')?.element,
  ).toMatchObject({ props: { guide: pmsHelpGuideRegistration } });
});
