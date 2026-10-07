import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { handleEvent, patchViolation } from './codex-hooks.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const git = (root, args) =>
  execFileSync('git', ['-C', root, ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'miy-hooks-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  git(root, ['init', '-q']);
  fs.writeFileSync(path.join(root, '.gitignore'), '.runtime/\n.env\n');
  fs.writeFileSync(path.join(root, 'file.txt'), 'original\n');
  git(root, ['add', '.']);
  git(root, [
    '-c',
    'user.name=Test',
    '-c',
    'user.email=test@invalid',
    '-c',
    'commit.gpgsign=false',
    'commit',
    '-qm',
    'fixture',
  ]);
  return root;
}
const event = (root, name, extra = {}) => ({
  cwd: root,
  session_id: 'synthetic-session',
  hook_event_name: name,
  ...extra,
});

test('patch policy blocks Git metadata and generated contracts, permits source changes', (t) => {
  const root = fixture(t);
  for (const name of [
    '.git/config',
    'packages/contracts/api.generated.d.ts',
    'apps/api/contracts_generated.py',
  ]) {
    assert.ok(
      patchViolation(
        root,
        `*** Begin Patch\n*** Add File: ${name}\n+x\n*** End Patch`,
      ),
    );
  }
  assert.equal(
    patchViolation(
      root,
      '*** Begin Patch\n*** Update File: file.txt\n@@\n-original\n+changed\n*** End Patch',
    ),
    null,
  );
  assert.throws(() => patchViolation(root, {}));
  assert.throws(() => patchViolation(root, 'unrecognized patch'));
  assert.throws(() =>
    patchViolation(root, '*** Begin Patch\n*** Delete File: file.txt'),
  );
});

test('patch uses session cwd and resolves existing symlink ancestors and rename destinations', (t) => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, 'nested'));
  fs.symlinkSync(path.join(root, '.git'), path.join(root, 'nested', 'alias'));
  assert.ok(
    patchViolation(
      root,
      '*** Begin Patch\n*** Update File: file.txt\n*** Move to: alias/config\n*** End Patch',
      path.join(root, 'nested'),
    ),
  );
  assert.ok(
    patchViolation(
      root,
      '*** Begin Patch\n*** Add File: ../.git/config\n+x\n*** End Patch',
      path.join(root, 'nested'),
    ),
  );
});

test('PreToolUse returns the documented deny schema; no guessed shell parsing', (t) => {
  const root = fixture(t);
  const output = handleEvent(
    event(root, 'PreToolUse', {
      tool_name: 'apply_patch',
      tool_input: {
        command: '*** Begin Patch\n*** Delete File: .git/config\n*** End Patch',
      },
    }),
  );
  assert.equal(output.hookSpecificOutput.permissionDecision, 'deny');
  assert.equal(output.hookSpecificOutput.hookEventName, 'PreToolUse');
  assert.deepEqual(
    handleEvent(
      event(root, 'PreToolUse', {
        tool_name: 'Bash',
        tool_input: { command: 'git status' },
      }),
    ),
    {},
  );
});

test('retired lifecycle events cannot run checks, create cache, or block completion', (t) => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, 'file.txt'), 'pre-existing change \n');
  for (const name of ['SessionStart', 'PostToolUse', 'Stop']) {
    assert.deepEqual(
      handleEvent(event(root, name), {
        resolveRoot: () => {
          throw Error('retired events must not inspect the workspace');
        },
      }),
      {},
    );
  }
  assert.equal(fs.existsSync(path.join(root, '.runtime')), false);
});

test('invalid patch input fails closed without exposing input or command errors', (t) => {
  const root = fixture(t);
  for (const input of [
    'private malformed input',
    JSON.stringify(
      event(root, 'PreToolUse', {
        tool_name: 'apply_patch',
        tool_input: { command: { private: 'sensitive-value' } },
      }),
    ),
  ]) {
    const result = spawnSync(
      'node',
      [path.join(ROOT, 'scripts/codex-hooks.mjs')],
      { input, encoding: 'utf8' },
    );
    assert.equal(result.status, 2);
    assert.equal(result.stdout, '');
    assert.ok(!result.stderr.includes('private'));
    assert.ok(!result.stderr.includes('sensitive-value'));
  }
});

test('native execpolicy rules allow PR operations and retain unrelated mutation denials', (t) => {
  if (spawnSync('codex', ['--version']).status !== 0) {
    t.skip(
      'Codex CLI unavailable; native integration must run on a Codex host',
    );
    return;
  }
  for (const [argv, denied, expectedDecision] of [
    [['gh', 'pr', 'create'], false, 'allow'],
    [['gh', 'pr', 'edit', '1'], false, 'allow'],
    [['gh', 'pr', 'merge', '1'], false, 'allow'],
    [['gh', 'pr', 'review', '1'], false, 'allow'],
    [['gh', 'pr', 'comment', '1'], false, 'allow'],
    [['gh', 'pr', 'close', '1'], false, 'allow'],
    [['gh', 'pr', 'reopen', '1'], false, 'allow'],
    [['gh', 'pr', 'view', '1'], false],
    [['gh', 'issue', 'edit', '1'], true],
    [['gh', 'issue', 'view', '1'], false],
    [['git', 'push', 'upstream', 'dev'], true],
    [['git', 'push', 'upstream', 'HEAD:main'], true],
    [['git', 'fetch', 'upstream'], false],
    [['git', 'push', 'origin', 'dev'], false],
    [['docker', 'compose', '-f', 'ops/compose/miy-prod.app.yml', 'up'], true],
    [
      ['docker', 'compose', '-f', 'ops/compose/miy-prod.app.yml', 'config'],
      false,
    ],
  ]) {
    const output = JSON.parse(
      execFileSync(
        'codex',
        [
          'execpolicy',
          'check',
          '--rules',
          path.join(ROOT, '.codex/rules/project.rules'),
          '--',
          ...argv,
        ],
        { encoding: 'utf8' },
      ),
    );
    assert.equal(output.decision === 'forbidden', denied, argv.join(' '));
    if (expectedDecision) {
      assert.equal(output.decision, expectedDecision, argv.join(' '));
    }
  }
});

test('checked-in hook config uses native synchronous events, bounded timeouts, and no trust bypass', () => {
  const config = JSON.parse(
    fs.readFileSync(path.join(ROOT, '.codex/hooks.json'), 'utf8'),
  );
  assert.deepEqual(Object.keys(config.hooks), ['PreToolUse']);
  assert.equal(config.hooks.PreToolUse[0].matcher, 'apply_patch');
  for (const groups of Object.values(config.hooks))
    for (const group of groups)
      for (const hook of group.hooks) {
        assert.equal(hook.type, 'command');
        assert.ok(hook.timeout > 0 && hook.timeout <= 5);
        assert.ok(!hook.async);
        assert.ok(hook.command.includes('scripts/codex-hooks.mjs'));
        assert.ok(!hook.command.includes('bypass'));
      }
});
