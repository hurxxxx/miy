import { afterEach, expect, it, vi } from 'vitest';
import { isValidElement } from 'react';
import { OFFICIAL_APP_IDS } from '@miy/contracts/app-contracts';
import {
  getAppRouteChrome,
  getAppRoutePattern,
} from '@miy/contracts/app-routes';
import { diagramsModule } from '@miy/official-suite-web/diagrams/module';
import { bentoModule } from '@miy/official-suite-web/bento/module';
import { mailModule } from '@miy/official-suite-web/mail/module';
import { docsModule } from '@miy/official-suite-web/docs/module';
import { pmsModule } from '@miy/official-suite-web/pms/module';
import { pmsModule as oldPms } from '@/src/app-modules/pms';
import { plannerModule } from '@miy/official-suite-web/planner/module';
import { plannerModule as oldPlanner } from '@/src/app-modules/planner';
import { meetingModule } from '@miy/official-suite-web/meeting/module';
import { meetingModule as oldMeeting } from '@/src/app-modules/meeting';
import { recordingModule } from '@miy/official-suite-web/recording/module';
import { recordingModule as oldRecording } from '@/src/app-modules/recording';
import { docsModule as oldDocs } from '@/src/app-modules/docs';
import { communityModule } from '@miy/official-suite-web/community/module';
import { communityModule as oldCommunity } from '@/src/app-modules/community';
import { whiteboardModule } from '@miy/official-suite-web/whiteboard/module';
import {
  lazyRoute as ownedLazy,
  LazyRouteErrorBoundary as OwnedBoundary,
  LazyRouteFallback as OwnedFallback,
} from '@miy/platform-web/routing';
import * as ownedRecovery from '@miy/platform-web/deployment';
import * as legacyRecovery from '@/src/platform/deployment/stale-asset-reload';
import { diagramsModule as oldDiagrams } from '@/src/app-modules/diagrams';
import { bentoModule as oldBento } from '@/src/app-modules/bento';
import { mailModule as oldMail } from '@/src/app-modules/mail';
import { whiteboardModule as oldWhiteboard } from '@/src/app-modules/whiteboard';
import { lazyRoute, LazyRouteErrorBoundary } from './lazy-route';
import { LazyRouteFallback } from './lazy-route-fallback';
import { OFFICIAL_APP_MODULES } from './official-app-modules';

// Importing a module must not evaluate its business screen before route render.
vi.mock('@miy/official-suite-web/diagrams/views/DiagramsView', () => {
  throw new Error('eager Diagrams screen');
});
vi.mock('@miy/official-suite-web/bento/views/BentoView', () => {
  throw new Error('eager Bento screen');
});
vi.mock('@miy/official-suite-web/mail/views/MailView', () => {
  throw new Error('eager Mail screen');
});
vi.mock('@miy/official-suite-web/whiteboard/views/WhiteboardView', () => {
  throw new Error('eager Whiteboard screen');
});
vi.mock('@miy/official-suite-web/community/views/CommunityView', () => {
  throw new Error('eager Community screen');
});
vi.mock('@miy/official-suite-web/docs/views/DocsView', () => {
  throw new Error('eager Docs screen');
});
vi.mock('@miy/official-suite-web/docs/views/DocsHtmlRenderPage', () => {
  throw new Error('eager Docs HTML screen');
});
vi.mock('@miy/official-suite-web/recording/views/RecordingView', () => {
  throw new Error('eager Recording screen');
});
vi.mock('@miy/official-suite-web/recording/views/RecordingDetailView', () => {
  throw new Error('eager Recording detail');
});
vi.mock('@miy/official-suite-web/meeting/views/MeetingView/MeetingView', () => {
  throw new Error('eager Meeting screen');
});
vi.mock(
  '@miy/official-suite-web/meeting/views/MeetingView/MeetingDetailView',
  () => {
    throw new Error('eager Meeting detail');
  },
);
vi.mock('@miy/official-suite-web/planner/views/PlannerView', () => {
  throw new Error('eager Planner screen');
});
vi.mock('@miy/official-suite-web/pms/views/PMSView', () => {
  throw new Error('eager PMS screen');
});
afterEach(() => vi.restoreAllMocks());
it('assembles the actual suite-owned modules without a second registry or eager UI', () => {
  expect(oldDiagrams).toBe(diagramsModule);
  expect(oldBento).toBe(bentoModule);
  expect(oldMail).toBe(mailModule);
  expect(oldWhiteboard).toBe(whiteboardModule);
  expect(oldCommunity).toBe(communityModule);
  expect(oldDocs).toBe(docsModule);
  expect(oldRecording).toBe(recordingModule);
  expect(oldMeeting).toBe(meetingModule);
  expect(oldPlanner).toBe(plannerModule);
  expect(oldPms).toBe(pmsModule);
  expect(OFFICIAL_APP_MODULES.map((m) => m.manifest.appBarItem.id)).toEqual(
    OFFICIAL_APP_IDS,
  );
  for (const module of [
    diagramsModule,
    bentoModule,
    mailModule,
    whiteboardModule,
    communityModule,
    docsModule,
    recordingModule,
    meetingModule,
    plannerModule,
    pmsModule,
  ])
    expect(
      OFFICIAL_APP_MODULES.find(
        (m) => m.manifest.appBarItem.id === module.manifest.appBarItem.id,
      ),
    ).toBe(module);
  expect(bentoModule.backgroundWorkSources).toHaveLength(1);
});
it('retains canonical route identity, chrome and the same route elements', () => {
  for (const [routes, ids] of [
    [diagramsModule.appRoutes, ['diagrams.root', 'diagrams.diagram']],
    [bentoModule.appRoutes, ['bento.root', 'bento.presentation']],
    [mailModule.globalRoutes, ['mail.root']],
    [whiteboardModule.appRoutes, ['whiteboard.root', 'whiteboard.board']],
    [whiteboardModule.globalRoutes, ['whiteboard.shared']],
    [communityModule.globalRoutes, ['community.root', 'community.post']],
    [
      docsModule.appRoutes,
      ['docs.root', 'docs.document', 'docs.document-html'],
    ],
    [docsModule.globalRoutes, ['docs.shared', 'docs.shared-html']],
    [recordingModule.appRoutes, ['recording.root', 'recording.detail']],
    [meetingModule.appRoutes, ['meeting.root', 'meeting.detail']],
    [plannerModule.globalRoutes, ['planner.root']],
  ] as const) {
    expect(routes.map((r) => r.path)).toEqual(
      ids.map((id) => getAppRoutePattern(id)),
    );
    expect(routes.map((r) => r.chrome)).toEqual(
      ids.map((id) => getAppRouteChrome(id)),
    );
    for (const route of routes)
      expect(isValidElement(route.element)).toBe(true);
  }
  expect(diagramsModule.appRoutes.every((r) => r.appId === 'diagrams')).toBe(
    true,
  );
  expect(bentoModule.appRoutes.every((r) => r.appId === 'bento')).toBe(true);
});
it('keeps the existing route runtime and reload handler objects through old entries', () => {
  expect(lazyRoute).toBe(ownedLazy);
  expect(LazyRouteErrorBoundary).toBe(OwnedBoundary);
  expect(LazyRouteFallback).toBe(OwnedFallback);
  for (const [key, value] of Object.entries(legacyRecovery))
    expect(ownedRecovery[key as keyof typeof ownedRecovery]).toBe(value);
});
it('shares one in-memory reload cooldown across old root initialization and new routes', () => {
  const replace = vi.fn();
  const runtime = {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    location: { href: 'https://synthetic.invalid/apps/diagrams', replace },
    history: { state: null, replaceState: vi.fn() },
  };
  const now = Date.now() + 120000;
  const error = new TypeError('Failed to fetch dynamically imported module');
  expect(
    legacyRecovery.maybeReloadForStaleAssetLoadError(error, runtime, {
      nowMs: () => now,
    }),
  ).toBe(true);
  expect(
    ownedRecovery.maybeReloadForStaleAssetLoadError(error, runtime, {
      nowMs: () => now + 1,
    }),
  ).toBe(false);
  expect(replace).toHaveBeenCalledTimes(1);
});
