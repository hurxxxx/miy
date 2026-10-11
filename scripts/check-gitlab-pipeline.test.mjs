import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

// The release selector is part of the pipeline contract, including in ci:harness.
import './release-validation.test.mjs';
import './prepare-validation-runtime.test.mjs';
import './build-ci-validation-image.test.mjs';

import {
  CODEX_ENTRYPOINT,
  CONTRACT,
  FEATURE_MR_RULE,
  RELEASE_MR_RULE,
  validateGitlabPipelineFiles,
  validateGitlabPipelineSource,
} from './check-gitlab-pipeline.mjs';

const repoRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const rootCi = path.join(repoRoot, '.gitlab-ci.yml');
const externalCi = path.join(repoRoot, 'ops/ci/ci-first.gitlab-ci.yml');

function readRootCi() {
  return fs.readFileSync(rootCi, 'utf8');
}

test('root and ops CI share one contract', () => {
  assert.equal(
    fs.readFileSync(rootCi, 'utf8'),
    fs.readFileSync(externalCi, 'utf8'),
  );
  assert.equal(validateGitlabPipelineFiles(repoRoot), CONTRACT);
});

test('CI has the feature review and release validation lanes', () => {
  const source = readRootCi();

  assert.ok(source.includes(FEATURE_MR_RULE));
  assert.ok(source.includes(RELEASE_MR_RULE));
  assert.ok(source.includes(CODEX_ENTRYPOINT));
  assert.ok(source.includes('codex_review:'));
  assert.ok(source.includes('release_validation:'));
  assert.ok(source.includes('contracts_publish:'));
});

test('contract rejects extra or weakened jobs', () => {
  const source = readRootCi();
  const mutations = [
    source.replace('  timeout: 2h\n', ''),
    source.replace('  timeout: 2h\n', '  timeout: 1h\n'),
    source.replace('  timeout: 2h\n', '  timeout: 24h\n'),
    source.replace(
      '  hooks:\n    pre_get_sources_script:\n      - umask 022\n',
      '',
    ),
    source.replace('      - umask 022\n', '      - umask 000\n'),
    source.replace('    GIT_STRATEGY: clone\n', '    GIT_STRATEGY: fetch\n'),
    source.replace('    - umask 022\n', ''),
    `${source}\nunexpected_check:\n  script: [true]\n`,
    source.replace(
      '  allow_failure: false\n  rules:\n',
      '  allow_failure: true\n  rules:\n',
    ),
    source.replace('$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME == "dev" && ', ''),
    source.replace('node scripts/release-validation.mjs ci', 'pnpm ci:harness'),
    source.replace(
      'prepare-validation-runtime.sh --postgres',
      'prepare-validation-runtime.sh',
    ),
    source.replace(
      'source scripts/ci/normalize-validation-postgres-dsn.sh',
      'true',
    ),
    source.replace('      - test-results/\n', ''),
    source.replace('      - api-test-results/\n', ''),
    source.replace('        - api-test-results/fast.xml\n', ''),
    source.replace('    access: maintainer\n', '    access: all\n'),
    source.replace("    MIY_API_PYTEST_WORKERS: '2'\n", ''),
    source.replace("    NODE_OPTIONS: '--max-old-space-size=3072'\n", ''),
    source.replace(
      "    VITEST_MAX_WORKERS: '1'",
      "    VITEST_MAX_WORKERS: '8'",
    ),
    source.replace(
      "    PLAYWRIGHT_WORKERS: '1'",
      "    PLAYWRIGHT_WORKERS: '8'",
    ),
    source.replace(
      'node scripts/release-validation.mjs ci',
      'node scripts/release-validation.mjs ci --mode fast',
    ),
  ];

  for (const mutated of mutations) {
    assert.throws(
      () => validateGitlabPipelineSource(mutated),
      /feature-codex-release-v1/,
    );
  }
});

test('contract rejects retired source project identifiers', () => {
  assert.throws(
    () =>
      validateGitlabPipelineSource(
        `${readRootCi()}\n# ${'dw'}${'dcc'} legacy\n`,
      ),
    /retired project identifiers/,
  );
});

test('API full diagnostics retain four reports and failures from every segment', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'miy-api-full-reports.'));
  try {
    const bin = path.join(root, 'bin');
    fs.mkdirSync(bin);
    fs.mkdirSync(path.join(root, 'apps/api'), { recursive: true });
    fs.mkdirSync(path.join(root, 'scripts/ci'), { recursive: true });
    fs.copyFileSync(
      path.join(repoRoot, 'scripts/ci/run-api-full-tests.sh'),
      path.join(root, 'scripts/ci/run-api-full-tests.sh'),
    );
    // Observe the wrapper's arguments without starting integration services.
    fs.writeFileSync(
      path.join(root, 'scripts/api-test-vm.sh'),
      '#!/usr/bin/env bash\nexec uv "$@"\n',
    );
    fs.writeFileSync(
      path.join(bin, 'uv'),
      `#!${process.execPath}
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
const report = args.find((arg) => arg.startsWith('--junitxml='))?.slice(11);
if (!report) process.exit(2);
fs.mkdirSync(path.dirname(report), { recursive: true });
fs.writeFileSync(report, '<testsuites/>');
fs.appendFileSync(process.env.CALLS_FILE, JSON.stringify({ args, cwd: process.cwd() }) + '\\n');
process.exit(path.basename(report) === 'fast.xml' ? Number(process.env.FAST_STATUS) : 0);
`,
      { mode: 0o700 },
    );
    const selectors = [
      'not slow and not external_integration and not migration',
      'slow and not external_integration and not migration',
      'migration',
      'external_integration',
    ];
    for (const fastStatus of [0, 1]) {
      const callsFile = path.join(root, `calls-${fastStatus}.jsonl`);
      const result = spawnSync(
        'bash',
        [path.join(root, 'scripts/ci/run-api-full-tests.sh')],
        {
          cwd: bin,
          encoding: 'utf8',
          timeout: 10_000,
          env: {
            PATH: `${bin}:${process.env.PATH}`,
            CALLS_FILE: callsFile,
            FAST_STATUS: String(fastStatus),
            MIY_API_PYTEST_WORKERS: '2',
          },
        },
      );
      assert.equal(result.error, undefined);
      assert.equal(result.status, fastStatus);
      const calls = fs
        .readFileSync(callsFile, 'utf8')
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line));
      assert.equal(calls.length, 4);
      // A later browser suite clears its output root. API evidence must survive.
      const browserOutput = path.join(root, 'test-results');
      fs.mkdirSync(browserOutput, { recursive: true });
      fs.writeFileSync(path.join(browserOutput, 'previous-run.txt'), 'browser');
      fs.rmSync(browserOutput, { recursive: true });
      for (const [index, name] of [
        'fast',
        'slow',
        'migration',
        'external',
      ].entries()) {
        const { args, cwd } = calls[index];
        const report = path.join(root, `api-test-results/${name}.xml`);
        assert.equal(cwd, path.join(root, 'apps/api'));
        assert.equal(args[args.lastIndexOf('-m') + 1], selectors[index]);
        assert.ok(args.includes('--tb=short'));
        assert.ok(args.includes('--show-capture=no'));
        assert.equal(args[args.indexOf('-o') + 1], 'junit_logging=no');
        assert.ok(args.includes(`--junitxml=${report}`));
        assert.ok(fs.existsSync(report));
      }
      assert.equal(calls[0].args[calls[0].args.indexOf('-n') + 1], '2');
      assert.ok(calls[0].args.includes('--dist=worksteal'));
      assert.match(
        result.stderr,
        /\[api-test-full\] pass external_integration/,
      );
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
