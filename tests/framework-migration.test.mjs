// Framework migration structural tests (node:test, stdlib only).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const REPO = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CHECKER = path.join(REPO, 'scripts', 'framework-check.mjs');
const run = (root) => spawnSync('node', [CHECKER, '--root', root], { encoding: 'utf8' });

// Copy framework-relevant files (working tree), not application code.
function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fw-mig-'));
  for (const rel of ['AGENTS.md', 'CLAUDE.md', 'README.md', 'FRAMEWORK_ADOPTION.md', 'framework.config.json',
    'docs', 'adapters', '.claude', '.github']) {
    fs.cpSync(path.join(REPO, rel), path.join(dir, rel), { recursive: true });
  }
  return dir;
}
const readConfig = (dir) => JSON.parse(fs.readFileSync(path.join(dir, 'framework.config.json'), 'utf8'));
const writeConfig = (dir, c) => fs.writeFileSync(path.join(dir, 'framework.config.json'), JSON.stringify(c, null, 2));
const taskText = (mode, impl) => `# T

- Status: APPROVED
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
${impl ? `- Implementer: ${impl}\n` : ''}${mode ? `- Authorization mode: ${mode}\n` : ''}- Authorization source: HUMAN LEAD approved boundary X
- Implementation authorized: YES

## Goal
g
## Scope
s
## Acceptance Criteria
a
## Required verification
v
`;
const addTask = (dir, text) => fs.writeFileSync(path.join(dir, 'docs/tasks/ZZ-fixture.md'), text);

test('real repo checker passes', () => {
  const r = run(REPO);
  assert.equal(r.status, 0, r.stdout);
});

test('new boundary task with enabled adapter passes', () => {
  const d = fixture();
  addTask(d, taskText('boundary', 'claude-code'));
  const r = run(d);
  assert.equal(r.status, 0, r.stdout);
});

test('new task with non-enabled implementer fails', () => {
  const d = fixture();
  addTask(d, taskText('boundary', 'gemini'));
  const r = run(d);
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /gemini is not an enabled adapter/);
});

test('new task missing Authorization mode fails', () => {
  const d = fixture();
  addTask(d, taskText(null, 'claude-code'));
  const r = run(d);
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /explicit Authorization mode/);
});

test('legacyTasks listing a nonexistent file fails', () => {
  const d = fixture();
  const c = readConfig(d);
  c.legacyTasks.files.push('does-not-exist.md');
  writeConfig(d, c);
  const r = run(d);
  assert.notEqual(r.status, 0);
  assert.match(r.stdout, /does-not-exist\.md/);
});

test('legacyTasks.files equals base-commit task files', () => {
  const c = readConfig(REPO);
  const ls = spawnSync('git', ['ls-tree', '--name-only', c.legacyTasks.baseCommit, 'docs/tasks/'], { cwd: REPO, encoding: 'utf8' });
  assert.equal(ls.status, 0, ls.stderr);
  const expected = ls.stdout.trim().split('\n').map((x) => path.basename(x))
    .filter((f) => f.endsWith('.md') && f !== '_template.md' && f !== 'AS-FW-UPGRADE-01.md').sort();
  assert.deepEqual([...c.legacyTasks.files].sort(), expected);
});
