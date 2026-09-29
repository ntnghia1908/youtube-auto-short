#!/usr/bin/env node
// Framework structural drift checker (shared across projects).
// Node stdlib only. Reads `framework.config.json` at the project root.
// It checks deterministic structure; it is not semantic review.
// Usage: node scripts/framework-check.mjs [--root <dir>]
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

function resolveRoot() {
  const i = process.argv.indexOf('--root');
  if (i !== -1) {
    const v = process.argv[i + 1];
    if (!v) { console.log('FAIL: --root requires a directory'); process.exit(1); }
    return path.resolve(v);
  }
  return path.dirname(path.dirname(fileURLToPath(import.meta.url)));
}

const ROOT = resolveRoot();
const errors = [];
const fail = (message) => errors.push(message);
const exists = (rel) => fs.existsSync(path.join(ROOT, rel));
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

function finish() {
  for (const e of errors) console.log(`FAIL: ${e}`);
  process.exit(1);
}

// ---- Config -------------------------------------------------------------
const CONFIG = 'framework.config.json';
const KNOWN_ADAPTERS = ['claude-code', 'copilot', 'codex'];

if (!exists(CONFIG)) { fail(`missing ${CONFIG}`); finish(); }
let config;
try { config = JSON.parse(read(CONFIG)); } catch (e) { fail(`${CONFIG}: invalid JSON (${e.message})`); finish(); }

const isStringArray = (v) => Array.isArray(v) && v.every((x) => typeof x === 'string' && x.length > 0);
if (config === null || typeof config !== 'object' || Array.isArray(config)) fail(`${CONFIG}: must be a JSON object`);
else {
  if (typeof config.frameworkVersion !== 'string' || !config.frameworkVersion) fail(`${CONFIG}: frameworkVersion must be a non-empty string`);
  if (!isStringArray(config.adapters)) fail(`${CONFIG}: adapters must be an array of strings`);
  else for (const a of config.adapters) if (!KNOWN_ADAPTERS.includes(a)) fail(`${CONFIG}: unknown adapter: ${a} (known: ${KNOWN_ADAPTERS.join(', ')})`);
  if ('requiredFiles' in config && !isStringArray(config.requiredFiles)) fail(`${CONFIG}: requiredFiles must be an array of strings`);
  if ('requiredTokens' in config) {
    const t = config.requiredTokens;
    if (t === null || typeof t !== 'object' || Array.isArray(t) || !Object.values(t).every(isStringArray)) {
      fail(`${CONFIG}: requiredTokens must be an object mapping file -> array of strings`);
    }
  }
  for (const key of ['taskDir', 'decisionDir']) {
    if (key in config && (typeof config[key] !== 'string' || !config[key])) fail(`${CONFIG}: ${key} must be a non-empty string`);
  }
}
if (errors.length) finish();

const adapters = config.adapters;
const extraFiles = config.requiredFiles ?? [];
const requiredTokens = config.requiredTokens ?? {};
const taskDir = (config.taskDir ?? 'docs/tasks').replace(/\/+$/, '');
const decisionDir = (config.decisionDir ?? 'docs/decisions').replace(/\/+$/, '');

// ---- Required files -----------------------------------------------------
const coreFiles = [
  'AGENTS.md',
  'docs/ai/workflow.md',
  'docs/ai/execution-profiles.md',
  'docs/ai/project-profile.md',
  'docs/ai/framework-history.md',
  'docs/workflow/current-state.md',
  'docs/tasks/_template.md',
  'FRAMEWORK_ADOPTION.md',
];
const adapterFiles = {
  'claude-code': ['CLAUDE.md', '.claude/rules/execution.md', '.claude/agents/implementer.md'],
  copilot: ['.github/copilot-instructions.md', '.github/agents/implementer.agent.md'],
  codex: [], // Codex CLI đọc AGENTS.md (luôn bắt buộc); không cần file riêng
};
const required = [...new Set([
  CONFIG,
  ...coreFiles,
  ...adapters.flatMap((a) => adapterFiles[a]),
  ...extraFiles,
])];
for (const rel of required) if (!exists(rel)) fail(`missing required file: ${rel}`);

// ---- Status / metadata --------------------------------------------------
function metadata(rel, key) {
  const line = read(rel).split('\n').find((x) => new RegExp(`^\\|\\s*${key}\\s*\\|`).test(x.trim()));
  return line ? line.split('|')[2].trim() : null;
}
const status = (rel) => metadata(rel, 'Status');

for (const rel of ['docs/ai/workflow.md', 'docs/ai/execution-profiles.md', 'docs/ai/project-profile.md', 'docs/ai/framework-history.md']) {
  if (exists(rel) && status(rel) !== 'CURRENT') fail(`${path.basename(rel)} must be CURRENT`);
}
if (exists('docs/workflow/current-state.md') && status('docs/workflow/current-state.md') !== 'OPERATIONAL STATE — NOT AUTHORITY') {
  fail('current-state.md has wrong operational status');
}

// ---- Version <-> config <-> history ------------------------------------
if (exists('docs/ai/workflow.md')) {
  const version = metadata('docs/ai/workflow.md', 'Version');
  if (!version) fail('workflow.md missing metadata row: | Version | ... |');
  else {
    if (version !== config.frameworkVersion) fail(`workflow.md Version ${version} does not match ${CONFIG} frameworkVersion ${config.frameworkVersion}`);
    if (exists('docs/ai/framework-history.md')) {
      const heading = `## v${version}`;
      const found = read('docs/ai/framework-history.md').split('\n').some((x) => x === heading || x.startsWith(`${heading} `));
      if (!found) fail(`framework-history.md missing entry for workflow Version ${version} (expected heading: ${heading})`);
    }
  }
}

// ---- Adoption record ----------------------------------------------------
if (exists('FRAMEWORK_ADOPTION.md')) {
  const a = read('FRAMEWORK_ADOPTION.md');
  for (const token of ['Adopted', 'Adapted', 'Not adopted']) if (!a.includes(token)) fail(`FRAMEWORK_ADOPTION.md missing section: ${token}`);
}

// ---- Adapter checks -----------------------------------------------------
if (adapters.includes('claude-code')) {
  if (exists('CLAUDE.md')) {
    const body = read('CLAUDE.md').replace(/<!--[\s\S]*?-->/g, '').trim();
    if (body !== '@AGENTS.md') fail('CLAUDE.md must be a minimal AGENTS.md bridge');
  }
  if (exists('.claude/rules/execution.md') && !read('.claude/rules/execution.md').includes('@../../docs/workflow/current-state.md')) {
    fail('.claude/rules/execution.md must import current-state.md');
  }
}

// ---- Project-specific required tokens ----------------------------------
for (const [rel, tokens] of Object.entries(requiredTokens)) {
  if (!exists(rel)) { fail(`requiredTokens: file not found: ${rel}`); continue; }
  const content = read(rel);
  for (const token of tokens) if (!content.includes(token)) fail(`${rel}: missing required token: ${token}`);
}

// ---- Unfilled template markers -----------------------------------------
for (const rel of required) {
  if (!exists(rel) || fs.statSync(path.join(ROOT, rel)).isDirectory()) continue;
  if (/<!--\s*FILL:/.test(read(rel))) fail(`${rel}: unfilled template marker: <!-- FILL: ... -->`);
}

// ---- Task contracts (docs/ai/workflow.md §4) ---------------------------
const taskFields = {
  'Status': ['DRAFT', 'APPROVED', 'IN_PROGRESS', 'READY'],
  'Type': null,
  'Change class': ['S1', 'S2'],
  'Owner': null,
  'Execution profile': ['single-agent', 'dual-agent'],
  'Implementation authorized': ['YES', 'NO'],
};
const taskSections = ['Goal', 'Scope', 'Acceptance Criteria', 'Required verification'];
const listMd = (dir) => (exists(dir) && fs.statSync(path.join(ROOT, dir)).isDirectory()
  ? fs.readdirSync(path.join(ROOT, dir)).filter((f) => f.endsWith('.md')).sort()
  : []);
const tasks = listMd(taskDir).filter((f) => f !== '_template.md');
for (const file of tasks) {
  const rel = `${taskDir}/${file}`;
  const lines = read(rel).split('\n');
  for (const [field, allowed] of Object.entries(taskFields)) {
    const line = lines.find((x) => x.startsWith(`- ${field}:`));
    const value = line ? line.slice(`- ${field}:`.length).trim() : '';
    if (!value) fail(`${rel}: missing field: ${field}`);
    else if (allowed && !allowed.includes(value)) fail(`${rel}: invalid ${field}: ${value}`);
  }
  for (const section of taskSections) if (!lines.includes(`## ${section}`)) fail(`${rel}: missing section: ${section}`);
}

// ---- Decision records ---------------------------------------------------
const decisionStatuses = ['PROPOSED', 'ACCEPTED', 'SUPERSEDED'];
const decisions = listMd(decisionDir);
for (const file of decisions) {
  const rel = `${decisionDir}/${file}`;
  const value = status(rel);
  if (!value) fail(`${rel}: missing metadata row: | Status | ... |`);
  else if (!decisionStatuses.some((s) => value.startsWith(s))) fail(`${rel}: invalid Status: ${value} (must start with ${decisionStatuses.join(', ')})`);
}

if (errors.length) finish();

for (const rel of required) console.log(`PASS: ${rel}`);
for (const file of tasks) console.log(`PASS: task contract ${taskDir}/${file}`);
for (const file of decisions) console.log(`PASS: decision record ${decisionDir}/${file}`);
console.log('PASS: framework structure');
