import nx from '@nx/eslint-plugin';

const moduleBoundaryOptions = {
  enforceBuildableLibDependency: true,
  allow: ['^.*/eslint(\\.base)?\\.config\\.[cm]?[jt]s$'],
  depConstraints: [{ sourceTag: '*', onlyDependOnLibsWithTags: ['*'] }],
};

export default [
  ...nx.configs['flat/base'],
  ...nx.configs['flat/typescript'],
  ...nx.configs['flat/javascript'],
  {
    ignores: [
      '**/dist',
      '**/out-tsc',
      '**/vite.config.*.timestamp*',
      '**/vitest.config.*.timestamp*',
    ],
  },
  {
    files: ['**/*.ts', '**/*.tsx', '**/*.js', '**/*.jsx'],
    rules: {
      '@nx/enforce-module-boundaries': ['error', moduleBoundaryOptions],
    },
  },
  {
    files: [
      'apps/official-suite/src/**/*.ts',
      'apps/official-suite/src/**/*.tsx',
    ],
    rules: {
      // OFF-002 stage zero: one named public source bridge, never arbitrary app imports.
      // Remove with the shared UI/business source extraction described by the suite owner.
      '@nx/enforce-module-boundaries': [
        'error',
        {
          ...moduleBoundaryOptions,
          allow: [
            ...moduleBoundaryOptions.allow,
            '@miy/web-official-suite-bridge',
          ],
        },
      ],
    },
  },
  {
    files: [
      '**/*.ts',
      '**/*.tsx',
      '**/*.cts',
      '**/*.mts',
      '**/*.js',
      '**/*.jsx',
      '**/*.cjs',
      '**/*.mjs',
    ],
    // Override or add rules here
    rules: {},
  },
  // Prevent direct imports of wrapped libraries in app code.
  // These should only be imported via @miy/ui wrappers.
  {
    files: ['apps/**/*.ts', 'apps/**/*.tsx'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: 'recharts',
              message: 'Use chart components from @miy/ui instead.',
            },
            {
              name: '@tanstack/react-table',
              message: 'Use DataTable from @miy/ui instead.',
            },
          ],
          patterns: [
            {
              group: ['@radix-ui/*'],
              message: 'Use primitives from @miy/ui instead.',
            },
            {
              group: [
                '@/src/components/views/**',
                '@/src/domains/**',
                '@/src/app-modules/*/routes',
                '@/src/app-modules/*/routes/**',
                '@/src/app-modules/*/api/**',
                '@/src/app-modules/*/lib/**',
                '@/src/app-modules/*/model/**',
                '@/src/app-modules/*/pages/**',
                '@/src/app-modules/*/sidebar',
                '@/src/app-modules/*/sidebar/**',
                '@/src/app-modules/*/ui/**',
                '@/src/app-modules/*/views',
                '@/src/app-modules/*/views/**',
              ],
              message:
                'Import app modules through their public registry/manifest boundary. App-specific views belong under app-modules/<appId>/views.',
            },
            {
              group: [
                '@fullcalendar/resource-*',
                '@fullcalendar/scrollgrid',
                '@fullcalendar/adaptive',
              ],
              message:
                'FullCalendar premium plugins are not licensed for this project. Only standard MIT plugins (core, react, daygrid, timegrid, list, interaction, luxon3) are allowed.',
            },
          ],
        },
      ],
    },
  },
];
