#!/usr/bin/env node
// Framework v4 structural drift checker for youtube-auto-short.
// Node stdlib only. It checks deterministic structure; it is not semantic review.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const required = [
  'AGENTS.md',
  'CLAUDE.md',
  'README.md',
  'docs/ai/workflow.md',
  'docs/ai/execution-profiles.md',
  'docs/ai/project-profile.md',
  'docs/workflow/current-state.md',
  'docs/tasks/_template.md',
  '.claude/rules/execution.md',
  '.claude/agents/implementer.md',
  '.github/copilot-instructions.md',
  'FRAMEWORK_ADOPTION.md',
];

function exists(rel) { return fs.existsSync(path.join(ROOT, rel)); }
function read(rel) { return fs.readFileSync(path.join(ROOT, rel), 'utf8'); }
function status(rel) {
  const line = read(rel).split('\n').find((x) => /^\|\s*Status\s*\|/.test(x.trim()));
  return line ? line.split('|')[2].trim() : null;
}
function fail(message) { errors.push(message); }
const errors = [];

for (const rel of required) if (!exists(rel)) fail(`missing required file: ${rel}`);

if (exists('docs/ai/workflow.md') && status('docs/ai/workflow.md') !== 'CURRENT') fail('workflow.md must be CURRENT');
if (exists('docs/ai/execution-profiles.md') && status('docs/ai/execution-profiles.md') !== 'CURRENT') fail('execution-profiles.md must be CURRENT');
if (exists('docs/ai/project-profile.md') && status('docs/ai/project-profile.md') !== 'CURRENT') fail('project-profile.md must be CURRENT');
if (exists('docs/workflow/current-state.md') && status('docs/workflow/current-state.md') !== 'OPERATIONAL STATE — NOT AUTHORITY') fail('current-state.md has wrong operational status');

if (exists('CLAUDE.md')) {
  const body = read('CLAUDE.md').replace(/<!--[\s\S]*?-->/g, '').trim();
  if (body !== '@AGENTS.md') fail('CLAUDE.md must be a minimal AGENTS.md bridge');
}

if (exists('.claude/rules/execution.md') && !read('.claude/rules/execution.md').includes('@../../docs/workflow/current-state.md')) {
  fail('.claude/rules/execution.md must import current-state.md');
}

if (exists('docs/ai/project-profile.md')) {
  const p = read('docs/ai/project-profile.md');
  if (!p.includes('youtube-vietnamese-dubber')) fail('project profile must declare the old dubber repo as reference-only');
  if (!p.includes('planned module boundaries')) fail('project profile must distinguish planned modules from implemented modules');
}

if (exists('FRAMEWORK_ADOPTION.md')) {
  const a = read('FRAMEWORK_ADOPTION.md');
  for (const token of ['Adopted', 'Adapted', 'Not adopted']) if (!a.includes(token)) fail(`FRAMEWORK_ADOPTION.md missing section: ${token}`);
}

// Task contracts: required metadata and sections from docs/ai/workflow.md §4.
const taskFields = {
  'Status': ['DRAFT', 'APPROVED', 'IN_PROGRESS', 'READY'],
  'Type': null,
  'Change class': ['S1', 'S2'],
  'Owner': null,
  'Execution profile': ['single-agent', 'dual-agent'],
  'Implementation authorized': ['YES', 'NO'],
};
const taskSections = ['Goal', 'Scope', 'Acceptance Criteria', 'Required verification'];
const tasks = exists('docs/tasks')
  ? fs.readdirSync(path.join(ROOT, 'docs/tasks')).filter((f) => f.endsWith('.md') && f !== '_template.md').sort()
  : [];
for (const file of tasks) {
  const rel = `docs/tasks/${file}`;
  const lines = read(rel).split('\n');
  for (const [field, allowed] of Object.entries(taskFields)) {
    const line = lines.find((x) => x.startsWith(`- ${field}:`));
    const value = line ? line.slice(`- ${field}:`.length).trim() : '';
    if (!value) fail(`${rel}: missing field: ${field}`);
    else if (allowed && !allowed.includes(value)) fail(`${rel}: invalid ${field}: ${value}`);
  }
  for (const section of taskSections) if (!lines.includes(`## ${section}`)) fail(`${rel}: missing section: ${section}`);
}

if (errors.length) {
  for (const e of errors) console.log(`FAIL: ${e}`);
  process.exit(1);
}

for (const rel of required) console.log(`PASS: ${rel}`);
for (const file of tasks) console.log(`PASS: task contract docs/tasks/${file}`);
console.log('PASS: framework structure');
