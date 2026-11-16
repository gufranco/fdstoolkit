import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, beforeEach, vi } from 'vitest';

import { start } from '../../src/fdstoolkit/ui/static/app.js';

const HTML = readFileSync(resolve('src/fdstoolkit/ui/static/index.html'), 'utf8');
const BODY = HTML.slice(HTML.indexOf('<body>') + '<body>'.length, HTML.indexOf('<script'));

export const FORMS = [
  {
    command: 'info',
    family: 'inspect',
    summary: 'Read a disk.',
    route: '/api/info',
    method: 'POST',
    fields: [
      { name: 'data', kind: 'file', required: true, accepts: '.fds,.qd' },
      { name: 'name', kind: 'auto', required: false, default: 'disk.fds' },
    ],
  },
  {
    command: 'consensus',
    family: 'repair',
    summary: 'Merge reads.',
    route: '/api/consensus',
    method: 'POST',
    fields: [{ name: 'images', kind: 'files', required: true, accepts: '' }],
  },
  {
    command: 'blank',
    family: 'container',
    summary: 'Make a blank disk.',
    route: '/api/blank',
    method: 'POST',
    fields: [
      { name: 'sides', kind: 'choice', required: false, options: ['1', '2'], default: 1, step: 1 },
      { name: 'passes', kind: 'number', required: false, minimum: 1, maximum: 20, step: 1, default: 1 },
      { name: 'ratio', kind: 'number', required: false, default: null },
      { name: 'formatted', kind: 'flag', required: false, default: true },
      { name: 'game_name', kind: 'text', required: true, min_length: 3, max_length: 3, default: null },
    ],
  },
  { command: 'status', family: 'hardware', summary: '', route: '/api/status', method: 'GET', fields: [] },
  {
    command: 'dump',
    family: 'hardware',
    summary: 'Dump a disk.',
    route: '/api/jobs/dump',
    method: 'POST',
    needs_hardware: true,
    fields: [{ name: 'sides', kind: 'choice', required: false, options: ['1', '2'], default: 1, step: 1 }],
  },
  {
    command: 'write',
    family: 'hardware',
    summary: 'Write a disk.',
    route: '/api/jobs/write',
    method: 'POST',
    needs_hardware: true,
    fields: [
      { name: 'data', kind: 'file', required: true, accepts: '.fds' },
      { name: 'confirm', kind: 'flag', required: false, hidden: true },
    ],
  },
  {
    command: 'lint',
    family: 'check',
    summary: 'Look for problems.',
    route: '/api/lint',
    method: 'POST',
    fields: [
      { name: 'reference', kind: 'file', required: false },
      { name: 'others', kind: 'files', required: false },
      { name: 'report', kind: 'auto', required: false, default: 'report.json' },
    ],
  },
  { command: 'oddity', family: 'elsewhere', summary: 'Not translated.', route: '/api/oddity', method: 'POST', fields: [] },
];

export const CATALOGUE = { forms: FORMS, families: ['inspect', 'repair', 'container', 'hardware'] };

let routes;
export let sent;

export function reply(status, body) {
  return { ok: status < 400, json: async () => body };
}

export function serve(extra = {}) {
  routes = {
    'GET /api/catalogue': () => reply(200, CATALOGUE),
    'GET /api/jobs/current': () => reply(200, { job: null }),
    'GET /api/hardware': () => reply(200, { connected: false, detail: 'none connected at 16D0:0AAA' }),
    ...extra,
  };
}

export async function settle() {
  for (let round = 0; round < 6; round += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

export async function open(command, extra) {
  serve(extra);
  window.history.replaceState(null, '', `#${command}`);
  await settle();
  await start();
  await settle();
}

export function panel() {
  return document.getElementById('panel');
}

export function field(name) {
  return panel().querySelector(`[data-field=${name}]`);
}

export function choose(node, files) {
  Object.defineProperty(node, 'files', { value: files, configurable: true });
  node.dispatchEvent(new Event('change'));
}

export async function run() {
  panel().querySelector('button.run').click();
  await settle();
}

export function useHarness() {
  beforeEach(() => {
    document.body.innerHTML = BODY;
    sent = [];
    globalThis.fetch = vi.fn(async (path, init) => {
      const key = `${init.method} ${path}`;
      sent = [...sent, { key, body: init.body === undefined ? undefined : JSON.parse(init.body) }];
      const route = routes[key];
      return route ? route(init) : reply(404, { detail: `no route ${key}` });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.replaceChildren();
  });
}
