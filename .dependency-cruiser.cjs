const fs = require('node:fs');
const path = require('node:path');

const appModulesRoot = path.join(__dirname, 'apps/web/src/app-modules');
const appModuleIds = fs
  .readdirSync(appModulesRoot, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)
  .sort();

const privateAppModuleEntry = (appId) =>
  `^apps/web/src/app-modules/${appId}/(?:api|lib|model|pages|routes|sidebar|ui|views)(?:[/.]|$)`;

module.exports = {
  forbidden: [
    {
      name: 'no-web-circular-dependencies',
      comment: 'Web source modules should not form dependency cycles.',
      severity: 'error',
      from: {
        path: '^(apps/(web|official-suite)/src|packages/(core-web|platform-web|official-suite-web)/src)',
      },
      to: {
        circular: true,
      },
    },
    {
      name: 'no-shared-or-official-metadata-imports-from-apps',
      comment:
        'Shared platform implementation and official UI source cannot depend on either application root.',
      severity: 'error',
      from: {
        path: '^packages/(core-web|platform-web|official-suite-web)/src',
      },
      to: { path: '^apps/' },
    },
    {
      name: 'no-platform-imports-from-official-ui',
      comment:
        'The common browser platform cannot acquire business UI dependencies.',
      severity: 'error',
      from: { path: '^packages/(core-web|platform-web)/src' },
      to: { path: '^packages/official-suite-web/src' },
    },
    {
      name: 'no-suite-recording-private-imports-outside-owner',
      comment:
        'Recording UI and recorder internals belong to the suite behind its public module.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/recording/|apps/web/src/app-modules/recording/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/recording/(api|views|recorder|routes|shell-nav)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-docs-private-imports-outside-owner',
      comment:
        'The complete Docs implementation stays behind its public API and module entry.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/docs/|apps/web/src/app-modules/docs/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/docs/(api|views|routes|sidebar)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-community-private-imports-outside-owner',
      comment:
        'Community implementation belongs to the suite behind its public module, editor and event entries.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/community/|apps/web/src/app-modules/community/|apps/web/src/platform/community/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/community/(api|views|routes|sidebar|editor/CommunityMarkdownEditor)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-whiteboard-private-imports-outside-owner',
      comment:
        'The complete Whiteboard implementation stays behind its public API and module entry.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/whiteboard/|apps/web/src/app-modules/whiteboard/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/whiteboard/(api|views|libraries|routes|sidebar)(?:[/.]|$)',
      },
    },
    {
      name: 'no-diagrams-private-imports-outside-owner',
      comment:
        'The suite Diagrams internals stay behind the public entry and existing owner compatibility entries.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/diagrams/|apps/web/src/app-modules/diagrams/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/diagrams/(api|views|routes|sidebar)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-bento-private-imports-outside-owner',
      comment:
        'Bento implementation is owned by the official suite behind its public entry.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/bento/|apps/web/src/app-modules/bento/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/bento/(api|views|routes|background-work|bento-route-paths)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-planner-private-imports-outside-owner',
      comment:
        'The complete Planner implementation stays behind public entries and existing compatibility exports.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/planner/|apps/web/src/app-modules/planner/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/planner/(api|views|routes|sidebar)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-pms-private-imports-outside-owner',
      comment:
        'The complete PMS implementation stays behind public entries and existing compatibility exports.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/pms/|apps/web/src/app-modules/pms/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/pms/(api|views|routes|sidebar|shell-nav)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-files-private-imports-outside-owner',
      comment:
        'Files implementation belongs to the suite and consumes the public common Chatbot entry.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/files/|apps/web/src/app-modules/files/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/files/(?!(?:index|module|messages)\\.ts$)',
      },
    },
    {
      name: 'no-platform-chatbot-private-imports-outside-owner',
      comment:
        'Common Chatbot implementation stays behind its explicit public entries and compatibility exports.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/platform-web/src/chatbot/|apps/web/src/app-modules/chatbot/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/platform-web/src/chatbot/(?!(?:index|module|manifest|state-types|messages)\\.ts$)',
      },
    },
    {
      name: 'no-suite-meeting-private-imports-outside-owner',
      comment:
        'The complete Meeting implementation stays behind public entries and existing owner compatibility exports.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/meeting/|apps/web/src/app-modules/meeting/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/meeting/(api|views|routes|sidebar)(?:[/.]|$)',
      },
    },
    {
      name: 'no-suite-video-chat-private-imports-outside-owner',
      comment:
        'The complete Video Chat implementation belongs to the suite behind public entries.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/video-chat/|apps/web/src/app-modules/video-chat/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/video-chat/(?!(?:index|module|messages)\\.ts$)',
      },
    },
    {
      name: 'no-suite-mail-private-imports-outside-owner',
      comment:
        'Mail implementation is owned by the official suite behind its public entry.',
      severity: 'error',
      from: {
        path: '^(apps|packages)/',
        pathNot:
          '^(packages/official-suite-web/src/mail/|apps/web/src/app-modules/mail/)|\\.spec\\.tsx?$',
      },
      to: {
        path: '^packages/official-suite-web/src/mail/(api|views|routes)(?:[/.]|$)',
      },
    },
    ...appModuleIds.map((appId) => ({
      name: `no-${appId}-private-imports-outside-owner`,
      comment:
        'App module internals must stay behind the app module public API.',
      severity: 'error',
      from: {
        path: '^apps/web/src',
        pathNot: `^apps/web/src/app-modules/${appId}/`,
      },
      to: {
        path: privateAppModuleEntry(appId),
      },
    })),
  ],
  options: {
    doNotFollow: {
      path: 'node_modules',
    },
    enhancedResolveOptions: {
      extensions: ['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json'],
      exportsFields: ['exports'],
      conditionNames: ['import', 'require', 'default'],
    },
    progress: {
      type: 'none',
    },
    tsConfig: {
      fileName: 'tsconfig.web-boundaries.json',
    },
  },
};
