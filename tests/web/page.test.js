import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { problemFor, renderResult, sentence, start } from '../../src/fdstoolkit/ui/static/app.js';
import { initialLanguage, rememberLanguage } from '../../src/fdstoolkit/ui/static/i18n.js';

const HTML = readFileSync(resolve('src/fdstoolkit/ui/static/index.html'), 'utf8');
const BODY = HTML.slice(HTML.indexOf('<body>') + '<body>'.length, HTML.indexOf('<script'));

const FORMS = [
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

const CATALOGUE = { forms: FORMS, families: ['inspect', 'repair', 'container', 'hardware'] };

let routes;
let sent;

function reply(status, body) {
  return { ok: status < 400, json: async () => body };
}

function serve(extra = {}) {
  routes = {
    'GET /api/catalogue': () => reply(200, CATALOGUE),
    'GET /api/jobs/current': () => reply(200, { job: null }),
    'GET /api/hardware': () => reply(200, { connected: false, detail: 'none connected at 16D0:0AAA' }),
    ...extra,
  };
}

async function settle() {
  for (let round = 0; round < 6; round += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

async function open(command, extra) {
  serve(extra);
  window.history.replaceState(null, '', `#${command}`);
  await settle();
  await start();
  await settle();
}

function panel() {
  return document.getElementById('panel');
}

function field(name) {
  return panel().querySelector(`[data-field=${name}]`);
}

function choose(node, files) {
  Object.defineProperty(node, 'files', { value: files, configurable: true });
  node.dispatchEvent(new Event('change'));
}

async function run() {
  panel().querySelector('button.run').click();
  await settle();
}

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

describe('start', () => {
  it('opens the command named in the address and orders the families', async () => {
    await open('blank');

    expect(panel().querySelector('.command-name').textContent).toBe('blank');
    expect([...document.querySelectorAll('#families button')].map((node) => node.dataset.family)).toEqual([
      'inspect',
      'repair',
      'container',
      'hardware',
      'check',
      'elsewhere',
    ]);
  });

  it('opens the first command when the address names none it knows', async () => {
    await open('missing');

    expect(panel().querySelector('.command-name').textContent).toBe('info');
  });

  it('says what went wrong when the catalogue cannot be read', async () => {
    await open('info', { 'GET /api/catalogue': () => reply(500, { detail: 'the server stopped' }) });

    expect(panel().querySelector('.reason').textContent).toBe('the server stopped');
  });

  it('shows an empty page when the catalogue carries no command and no family order', async () => {
    await open('info', { 'GET /api/catalogue': () => reply(200, { forms: [] }) });

    expect(panel().textContent).toBe('Choose a command on the left.');
    expect(document.querySelector('#commands .no-match')).not.toBeNull();
  });
});

describe('the command list', () => {
  it('switches to the first command of a family', async () => {
    await open('info');

    document.querySelector('#families [data-family=repair]').click();

    expect(panel().querySelector('.command-name').textContent).toBe('consensus');
    expect(window.location.hash).toBe('#consensus');
  });

  it('opens the command clicked in the list', async () => {
    await open('dump');

    document.querySelectorAll('#commands button')[2].click();

    expect(panel().querySelector('.command-name').textContent).toBe('write');
  });

  it('filters across families and opens the first match', async () => {
    await open('info');
    const search = document.getElementById('search');

    search.value = 'wri';
    search.dispatchEvent(new Event('input'));

    expect(panel().querySelector('.command-name').textContent).toBe('write');
  });

  it('keeps the open command when the filter matches nothing', async () => {
    await open('info');
    const search = document.getElementById('search');

    search.value = 'nothing-like-this';
    search.dispatchEvent(new Event('input'));

    expect(document.querySelector('#commands .no-match').textContent).toBe('No command matches that.');
    expect(panel().querySelector('.command-name').textContent).toBe('info');
  });

  it('follows the address when it changes', async () => {
    await open('info');

    window.history.replaceState(null, '', '#blank');
    window.dispatchEvent(new Event('hashchange'));

    expect(panel().querySelector('.command-name').textContent).toBe('blank');
  });

  it('keeps working when the address cannot be rewritten', async () => {
    await open('info');
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {
      throw new Error('blocked');
    });

    document.querySelector('#families [data-family=container]').click();

    expect(panel().querySelector('.command-name').textContent).toBe('blank');
  });

  it('falls back to the summary the catalogue carries when no translation exists', async () => {
    await open('oddity');

    expect(panel().querySelector('.summary').textContent).toBe('Not translated.');
  });
});

describe('languages', () => {
  it('translates the page and remembers the choice', async () => {
    await open('info');

    document.querySelector('[data-language=ja]').click();

    expect(document.documentElement.lang).toBe('ja');
    expect(document.querySelector('[data-language=ja]').getAttribute('aria-pressed')).toBe('true');
    expect(window.localStorage.getItem('fdstoolkit.language')).toBe('ja');
    document.querySelector('[data-language=en]').click();
  });

  it('falls back to English for a language it does not carry', async () => {
    await open('info');
    const unknown = document.createElement('button');
    unknown.dataset.language = 'xx';
    document.querySelector('.languages').append(unknown);
    await start();

    unknown.click();

    expect(document.querySelector('[data-i18n=title]').textContent).toBe('Famicom Disk System Toolkit');
    document.querySelector('[data-language=en]').click();
  });
});

describe('the form', () => {
  it('builds every kind of control with its limits and help', async () => {
    await open('blank');

    expect(field('sides').tagName).toBe('SELECT');
    expect(field('sides').value).toBe('1');
    expect(field('passes').min).toBe('1');
    expect(field('passes').max).toBe('20');
    expect(field('ratio').step).toBe('any');
    expect(field('formatted').checked).toBe(true);
    expect(field('game_name').minLength).toBe(3);
    expect(field('game_name').maxLength).toBe(3);
    expect(field('game_name').required).toBe(true);
    expect(panel().textContent).toContain('Fill in game name, then press the button.');
  });

  it('says a command needs nothing when it has no fields', async () => {
    await open('status');

    expect(panel().textContent).toContain('This command needs nothing from you. Press the button.');
  });

  it('names the file chosen and what the field accepts', async () => {
    await open('info');
    const node = field('data');

    choose(node, [new File([new Uint8Array([1])], 'game.fds')]);

    expect(panel().querySelector('.file-name').textContent).toBe('game.fds');
    expect(panel().textContent).toContain('Expects .fds, .qd');
    choose(node, []);
    expect(panel().querySelector('.file-name').textContent).toBe('No file chosen');
  });

  it('explains a value as soon as it goes out of range', async () => {
    await open('blank');
    const node = field('passes');
    node.checkValidity = () => false;
    Object.defineProperty(node, 'validity', { value: { rangeOverflow: true }, configurable: true });

    node.dispatchEvent(new Event('input'));

    expect(node.closest('label').classList.contains('missing')).toBe(true);
    expect(node.closest('label').querySelector('.field-problem').textContent).toBe('Must be 20 or less.');
  });
});

describe('running a command', () => {
  it('refuses to run with a required field empty', async () => {
    await open('info');

    await run();

    expect(panel().querySelector('.output .banner').textContent).toBe('Still needed: data');
    expect(sent.filter((entry) => entry.key === 'POST /api/info')).toEqual([]);
  });

  it('refuses to run with a value out of range', async () => {
    await open('blank');
    field('game_name').value = 'SMB';
    const node = field('passes');
    node.checkValidity = () => false;
    Object.defineProperty(node, 'validity', { value: { rangeUnderflow: true }, configurable: true });

    await run();

    expect(panel().querySelector('.output .reason').textContent).toBe('passes: Must be 1 or more.');
  });

  it('sends typed values and shows the answer', async () => {
    await open('blank', { 'POST /api/blank': () => reply(200, { headline: 'made a blank disk', ok: true }) });
    field('game_name').value = 'SMB';
    field('sides').value = '2';
    field('ratio').value = '';

    await run();

    const call = sent.find((entry) => entry.key === 'POST /api/blank');
    expect(call.body).toEqual({ sides: 2, passes: 1, formatted: true, game_name: 'SMB' });
    expect(panel().querySelector('.output .banner').textContent).toBe('made a blank disk');
    expect(panel().querySelector('button.run').disabled).toBe(false);
  });

  it('encodes the chosen file and derives the output name from it', async () => {
    await open('info', { 'POST /api/info': () => reply(200, { text: 'Game name: SMB' }) });
    choose(field('data'), [new File([new Uint8Array([1, 2])], 'smb.qd')]);

    await run();

    const call = sent.find((entry) => entry.key === 'POST /api/info');
    expect(call.body).toEqual({ data: 'AQI=', name: 'smb.fds' });
  });

  it('sends every file of a many-file field', async () => {
    await open('consensus', { 'POST /api/consensus': () => reply(200, { headline: 'merged' }) });
    choose(field('images'), [new File([new Uint8Array([1])], 'a.fds'), new File([new Uint8Array([2])], 'b.fds')]);

    await run();

    const call = sent.find((entry) => entry.key === 'POST /api/consensus');
    expect(call.body).toEqual({ images: ['AQ==', 'Ag=='] });
  });

  it('leaves out optional files nobody chose and keeps the default name', async () => {
    await open('lint', { 'POST /api/lint': () => reply(200, { headline: 'clean', ok: true }) });

    await run();

    const call = sent.find((entry) => entry.key === 'POST /api/lint');
    expect(call.body).toEqual({ report: 'report.json' });
  });

  it('uses GET for a command that reads only', async () => {
    await open('status', { 'GET /api/status': () => reply(200, { headline: 'healthy', ok: true }) });

    await run();

    expect(panel().querySelector('.output .banner').textContent).toBe('healthy');
  });

  it('says the server failed when its answer is not a result', async () => {
    await open('status', { 'GET /api/status': () => ({ ok: false, status: 500, json: async () => JSON.parse('Internal Server Error') }) });

    await run();

    expect(panel().querySelector('.output .reason').textContent).toBe(
      'The server answered 500 with something that is not a result. Its terminal shows what went wrong.',
    );
  });

  it('reports a refusal with the reason and a hint', async () => {
    await open('blank', { 'POST /api/blank': () => reply(422, { detail: [{ loc: ['body', 'game_name'], msg: 'too long' }] }) });
    field('game_name').value = 'SMB';

    await run();

    expect(panel().querySelector('.output .reason').textContent).toBe('game name: too long');
  });
});

describe('the drive commands', () => {
  const done = {
    id: 'j1',
    command: 'dump',
    writes: false,
    state: 'done',
    steps: [],
    prompt: '',
    result: { name: 'dump.fds', data: 'AA==', size: 1, grade: 'clean' },
    error: '',
  };

  it('says whether the stick is connected, with the detail as a sentence', async () => {
    await open('dump');

    expect(panel().querySelector('.banner.bad').textContent).toBe(
      'No FDSStick is connected, so this command cannot reach a real drive. None connected at 16D0:0AAA',
    );
  });

  it('says when the stick is connected', async () => {
    await open('dump', { 'GET /api/hardware': () => reply(200, { connected: true, detail: '1 device(s) connected' }) });

    expect(panel().querySelector('.banner.good').textContent).toBe('An FDSStick is connected. 1 device(s) connected');
  });

  it('says when the stick state cannot be read', async () => {
    await open('dump', { 'GET /api/hardware': () => reply(500, { detail: 'hid failed' }) });

    expect(panel().querySelector('.banner.bad').textContent).toBe('The device state could not be read: Hid failed');
  });

  it('runs a dump as a job with no erase dialog', async () => {
    await open('dump', { 'POST /api/jobs/dump': () => reply(200, done) });

    await run();

    expect(document.querySelector('dialog')).toBeNull();
    expect(panel().querySelector('.output a').download).toBe('dump.fds');
  });

  it('writes nothing when the erase is cancelled', async () => {
    await open('write');
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);

    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .plain').click();
    await settle();

    expect(panel().querySelector('.output .banner').textContent).toBe('Cancelled. Nothing was written.');
    expect(sent.filter((entry) => entry.key === 'POST /api/jobs/write')).toEqual([]);
  });

  it('confirms the erase in the request once the dialog agrees', async () => {
    const written = { ...done, command: 'write', writes: true, result: { headline: 'written', ok: true } };
    await open('write', { 'POST /api/jobs/write': () => reply(200, written) });
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);

    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .danger').click();
    await settle();

    const call = sent.find((entry) => entry.key === 'POST /api/jobs/write');
    expect(call.body).toEqual({ data: 'AQ==', confirm: true });
    expect(panel().querySelector('.output .banner').textContent).toBe('written');
  });

  it('shows a failed answer to the turn prompt without losing the job', async () => {
    const waiting = { ...done, state: 'waiting', prompt: 'turn the disk over', result: null };
    const failed = { ...waiting, state: 'failed', prompt: '', error: 'declined' };
    let polls = 0;
    await open('dump', {
      'POST /api/jobs/dump': () => reply(200, waiting),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? failed : waiting);
      },
      'POST /api/jobs/j1/answer': () => reply(409, { detail: 'that job is not waiting for an answer' }),
    });

    await run();
    panel().querySelector('.turn .plain').click();
    await settle();

    expect(panel().querySelector('.output').textContent).toContain('that job is not waiting for an answer');
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('declined'), {
      timeout: 3000,
    });
  });

  it('stops a job that can stop and reports a stop the server refused', async () => {
    const measuring = { ...done, state: 'running', stoppable: true, result: null };
    let polls = 0;
    await open('dump', {
      'POST /api/jobs/dump': () => reply(200, measuring),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? { ...measuring, state: 'failed', error: 'stopped' } : measuring);
      },
      'POST /api/jobs/j1/stop': () => reply(409, { detail: 'that job cannot be stopped' }),
    });

    await run();
    panel().querySelector('.job .dialog-actions .plain').click();
    await settle();

    expect(sent.some((entry) => entry.key === 'POST /api/jobs/j1/stop')).toBe(true);
    expect(panel().querySelector('.output').textContent).toContain('that job cannot be stopped');
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('stopped'), {
      timeout: 3000,
    });
  });

  it('asks before the page closes while a job writes', async () => {
    const writing = { ...done, command: 'write', writes: true, state: 'running', result: null };
    let polls = 0;
    await open('write', {
      'POST /api/jobs/write': () => reply(200, writing),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? { ...writing, state: 'failed', error: 'stalled' } : writing);
      },
    });
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);
    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .danger').click();
    await settle();

    const leaving = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(leaving);

    expect(leaving.defaultPrevented).toBe(true);
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('stalled'), {
      timeout: 3000,
    });
  });

  it('picks up a job that is already running', async () => {
    await open('info', { 'GET /api/jobs/current': () => reply(200, { job: done }) });

    expect(panel().querySelector('.command-name').textContent).toBe('dump');
    expect(panel().querySelector('.output a').download).toBe('dump.fds');
  });

  it('ignores a running job for a command the page does not offer', async () => {
    await open('info', { 'GET /api/jobs/current': () => reply(200, { job: { ...done, command: 'gone' } }) });

    expect(panel().querySelector('.command-name').textContent).toBe('info');
  });
});

describe('problemFor', () => {
  const limits = { minimum: 1, maximum: 20, min_length: 3, max_length: 3 };

  function failing(validity) {
    return { checkValidity: () => false, validity, validationMessage: 'the browser says no' };
  }

  it('says nothing for a valid value or a node with no validation', () => {
    expect(problemFor({ checkValidity: () => true }, limits)).toBe('');
    expect(problemFor({}, limits)).toBe('');
  });

  it('names every kind of problem in the page language', () => {
    expect(problemFor(failing({ tooShort: true }), limits)).toBe('Needs at least 3 characters.');
    expect(problemFor(failing({ tooLong: true }), limits)).toBe('No more than 3 characters.');
    expect(problemFor(failing({ badInput: true }), limits)).toBe('That is not the shape this field expects.');
    expect(problemFor(failing({ valueMissing: true }), limits)).toBe('This one is required.');
    expect(problemFor(failing({}), limits)).toBe('the browser says no');
  });
});

describe('sentence', () => {
  it('capitalises the first letter and leaves the rest alone', () => {
    expect(sentence('none connected at 16D0:0AAA')).toBe('None connected at 16D0:0AAA');
    expect(sentence('')).toBe('');
  });
});

describe('the rest of the result layouts', () => {
  it('lists a change that carries no marks, only its two values', () => {
    const target = document.createElement('div');

    renderResult(target, { changes: [{ left: 'A', right: 'B', moved: false }] });

    expect(target.querySelector('.change-marks')).toBeNull();
    expect(target.querySelector('.change-values').textContent).toContain('A');
  });

  it('lays out a list that mixes values and records as pairs', () => {
    const target = document.createElement('div');

    renderResult(target, { mixed: [1, { side: 0 }] });

    expect(target.querySelector('dl dl')).not.toBeNull();
  });

  it('offers a file on its own when nothing else came with it', () => {
    const target = document.createElement('div');

    renderResult(target, { headline: '', file: { name: 'before.fds', data: 'AA==', size: 1 } });

    expect(target.querySelector('a').download).toBe('before.fds');
    expect(target.querySelector('dl')).toBeNull();
  });
});

describe('initialLanguage', () => {
  it('keeps a remembered language the page carries', () => {
    window.localStorage.setItem('fdstoolkit.language', 'ja');

    expect(initialLanguage()).toBe('ja');
    window.localStorage.removeItem('fdstoolkit.language');
  });

  it('follows the browser when nothing is remembered', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('ja-JP');

    expect(initialLanguage()).toBe('ja');
  });

  it('falls back to English for a browser language it does not carry, or none', () => {
    const language = vi.spyOn(navigator, 'language', 'get').mockReturnValue('pt-BR');
    expect(initialLanguage()).toBe('en');

    language.mockReturnValue('');
    expect(initialLanguage()).toBe('en');
  });

  it('works when storage is blocked', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });

    rememberLanguage('ja');

    expect(initialLanguage()).toBe('en');
  });
});
