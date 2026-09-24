import { DICTIONARIES, FALLBACK, initialLanguage, rememberLanguage } from './i18n.js';

let state = {
  language: initialLanguage(),
  forms: [],
  filter: '',
  family: '',
  command: '',
};

function update(changes) {
  state = { ...state, ...changes };
}

function t(key) {
  const table = DICTIONARIES[state.language] || DICTIONARIES[FALLBACK];
  return table[key] || '';
}

function label(key, fallback) {
  return t(key) || fallback;
}

function families() {
  return [...new Set(state.forms.map((form) => form.family))].toSorted();
}

function visible() {
  const needle = state.filter.trim().toLowerCase();
  if (needle) {
    return state.forms.filter((form) => form.command.includes(needle));
  }
  return state.forms.filter((form) => form.family === state.family);
}

function selected() {
  return state.forms.find((form) => form.command === state.command) || null;
}

function element(tag, properties) {
  return Object.assign(document.createElement(tag), properties);
}

export function words(key) {
  return key.replace(/_/g, ' ');
}

function applyLanguage() {
  document.documentElement.lang = state.language;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-language]').forEach((node) => {
    node.setAttribute('aria-pressed', String(node.dataset.language === state.language));
  });
  render();
}

async function encodeFile(file) {
  const buffer = await file.arrayBuffer();
  return window.btoa(Array.from(new Uint8Array(buffer), (byte) => String.fromCharCode(byte)).join(''));
}

export function explain(detail) {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const where = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join(' ') : '';
        return where ? `${words(where)}: ${item.msg}` : item.msg;
      })
      .join('. ');
  }
  return JSON.stringify(detail);
}

async function call(path, method, body) {
  const answer = await fetch(path, {
    method,
    headers: method === 'GET' ? {} : { 'content-type': 'application/json' },
    body: method === 'GET' ? undefined : JSON.stringify(body),
  });
  const payload = await answer.json();
  if (!answer.ok) {
    throw new Error(explain(payload.detail));
  }
  return payload;
}

export function bytes(size) {
  const kib = 1024;
  return size < kib ? `${size} B` : `${(size / kib).toFixed(1)} KiB`;
}

function download(entry) {
  const link = element('a', {
    href: 'data:application/octet-stream;base64,' + entry.data,
    download: entry.name,
    className: 'download',
    textContent: `${t('button.download')} ${entry.name}`,
  });
  const row = element('div', { className: 'download-row' });
  row.append(link, element('span', { className: 'download-size', textContent: bytes(entry.size) }));
  return row;
}

export function scalar(value) {
  if (value === null || value === undefined) {
    return t('value.none');
  }
  if (typeof value === 'boolean') {
    return value ? t('value.yes') : t('value.no');
  }
  return String(value);
}

function isScalar(value) {
  return value === null || value === undefined || typeof value !== 'object';
}

function table(rows) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const node = element('table', { className: 'grid' });
  const head = element('tr', {});
  head.append(...columns.map((column) => element('th', { textContent: words(column) })));
  const body = rows.map((row) => {
    const line = element('tr', {});
    line.append(...columns.map((column) => element('td', { textContent: scalar(row[column]) })));
    return line;
  });
  node.append(head, ...body);
  return node;
}

const PROSE_LENGTH = 24;

function isRecord(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function isChange(rows) {
  return rows.every((row) => isRecord(row) && 'left' in row && 'right' in row);
}

export function isProse(value) {
  return typeof value === 'string' && (value.includes(' ') || value.length > PROSE_LENGTH);
}

function chip(key, value) {
  const node = element('span', { className: 'chip' });
  if (typeof value === 'boolean') {
    node.append(element('span', { className: 'chip-flag', textContent: words(key) }));
    return node;
  }
  node.append(
    element('span', { className: 'chip-key', textContent: words(key) }),
    element('span', { className: 'chip-value', textContent: scalar(value) }),
  );
  return node;
}

function side(key, value) {
  const node = element('span', { className: 'side' });
  node.append(
    element('span', { className: 'side-key', textContent: words(key) }),
    element('span', { className: 'side-value', textContent: scalar(value) }),
  );
  return node;
}

function change(row) {
  const item = element('li', { className: 'change' });
  const rest = Object.entries(row)
    .filter(([key]) => key !== 'left' && key !== 'right')
    .filter(([, value]) => value !== false);
  const marks = rest.filter(([, value]) => !isProse(value));
  const prose = rest.filter(([, value]) => isProse(value));
  if (marks.length) {
    const head = element('p', { className: 'change-marks' });
    head.append(...marks.map(([key, value]) => chip(key, value)));
    item.append(head);
  }
  prose.forEach(([, value]) => {
    item.append(element('p', { className: 'change-note', textContent: scalar(value) }));
  });
  const values = element('p', { className: 'change-values' });
  values.append(side('left', row.left), side('right', row.right));
  item.append(values);
  return item;
}

function changes(rows) {
  const list = element('ul', { className: 'changes' });
  list.append(...rows.map(change));
  return list;
}

function pairs(value) {
  const list = element('dl', { className: 'pairs' });
  Object.entries(value).forEach(([key, item]) => {
    const body = describe(item);
    const label = element('dt', { textContent: words(key) });
    if (body.classList.contains('wide')) {
      label.classList.add('wide');
    }
    list.append(label, body);
  });
  return list;
}

export function describe(value) {
  if (isScalar(value)) {
    return element('dd', { textContent: scalar(value) });
  }
  const holder = element('dd', {});
  if (Array.isArray(value)) {
    if (!value.length) {
      holder.append(element('span', { className: 'quiet', textContent: t('value.empty') }));
      return holder;
    }
    if (value.every(isScalar)) {
      holder.append(element('span', { textContent: value.map(scalar).join(', ') }));
      return holder;
    }
    if (value.every(isRecord)) {
      holder.classList.add('wide');
      holder.append(isChange(value) ? changes(value) : table(value));
      return holder;
    }
  }
  holder.append(pairs(value));
  return holder;
}

function raw(payload) {
  const box = element('details', { className: 'raw' });
  box.append(
    element('summary', { textContent: t('result.raw') }),
    element('pre', { textContent: JSON.stringify(payload, null, 2) }),
  );
  return box;
}

function banner(kind, message) {
  return element('p', { className: `banner ${kind}`, textContent: message });
}

const SAID_IN_BANNER = new Set(['headline', 'ok']);

export function verdict(payload) {
  const negative = Boolean(payload) && payload.ok === false;
  const headline = payload && typeof payload.headline === 'string' ? payload.headline.trim() : '';
  if (headline) {
    return banner(negative ? 'warn' : 'good', headline);
  }
  return banner(negative ? 'warn' : 'good', t(negative ? 'state.findings' : 'state.done'));
}

function carries(value) {
  return value !== null && value !== undefined && !(Array.isArray(value) && !value.length);
}

export function reported(payload) {
  const spoken = typeof payload.headline === 'string' && payload.headline.trim();
  return Object.fromEntries(
    Object.entries(payload)
      .filter(([key]) => !SAID_IN_BANNER.has(key))
      .filter(([, value]) => !spoken || carries(value)),
  );
}

export function isDownload(entry) {
  return Boolean(entry)
    && typeof entry.data === 'string'
    && typeof entry.size === 'number'
    && typeof entry.name === 'string';
}

export function renderResult(target, payload) {
  if (isDownload(payload)) {
    target.replaceChildren(banner('good', t('state.file')), download(payload));
    return;
  }
  if (payload && Array.isArray(payload.files) && payload.files.length && payload.files.every(isDownload)) {
    target.replaceChildren(banner('good', t('state.files').replace('{n}', String(payload.files.length))));
    target.append(...payload.files.map(download));
    return;
  }
  if (payload && typeof payload.text === 'string') {
    target.replaceChildren(verdict(payload), element('pre', { textContent: payload.text }));
    return;
  }
  if (payload && typeof payload === 'object') {
    const rest = reported(payload);
    const middle = Object.keys(rest).length ? [pairs(rest)] : [];
    target.replaceChildren(verdict(payload), ...middle, raw(payload));
    return;
  }
  target.replaceChildren(
    banner('good', t('state.done')),
    element('pre', { textContent: JSON.stringify(payload, null, 2) }),
  );
}

function emptyResult(form) {
  const box = element('div', { className: 'empty' });
  const needed = form.fields
    .filter((field) => field.required && field.kind !== 'auto')
    .map((field) => words(field.name));
  box.append(element('p', { textContent: t('result.empty') }));
  if (needed.length) {
    box.append(element('p', {
      className: 'quiet',
      textContent: t('result.needs').replace('{fields}', needed.join(', ')),
    }));
  }
  box.append(element('p', { className: 'quiet', textContent: t('result.local') }));
  return box;
}

function chosen(node) {
  const files = Array.from(node.files || []);
  return files.length ? files.map((file) => file.name).join(', ') : t('file.none');
}

function fileControl(field) {
  const node = element('input', {
    type: 'file',
    multiple: field.kind === 'files',
    className: 'offscreen',
    accept: field.accepts,
  });
  const name = element('span', { className: 'file-name', textContent: t('file.none') });
  const box = element('span', { className: 'file-box' });
  box.append(
    element('span', {
      className: 'file-button',
      textContent: t(field.kind === 'files' ? 'file.many' : 'file.one'),
    }),
    name,
  );
  node.addEventListener('change', () => {
    name.textContent = chosen(node);
    node.closest('label').classList.remove('missing');
  });
  return { node, box };
}

function bound(node, field) {
  if (field.minimum !== null && field.minimum !== undefined) {
    node.min = String(field.minimum);
  }
  if (field.maximum !== null && field.maximum !== undefined) {
    node.max = String(field.maximum);
  }
  if (field.min_length !== null && field.min_length !== undefined) {
    node.minLength = field.min_length;
  }
  if (field.max_length !== null && field.max_length !== undefined) {
    node.maxLength = field.max_length;
  }
  if (field.required) {
    node.required = true;
  }
  return node;
}

function input(field) {
  if (field.kind === 'flag') {
    return element('input', { type: 'checkbox', checked: Boolean(field.default) });
  }
  const shown = field.default === null || field.default === undefined ? '' : String(field.default);
  if (field.kind === 'number') {
    return bound(
      element('input', { type: 'number', step: String(field.step || 'any'), value: shown }),
      field,
    );
  }
  if (field.kind === 'choice') {
    const select = element('select', { value: shown });
    select.append(...field.options.map((option) => element('option', {
      value: option,
      textContent: option === '' ? t('flux.auto') : option,
      selected: option === shown,
    })));
    return select;
  }
  return bound(element('input', { type: 'text', value: shown }), field);
}

export function problemFor(node, field) {
  if (typeof node.checkValidity !== 'function' || node.checkValidity()) {
    return '';
  }
  const state = node.validity;
  if (state.rangeUnderflow) {
    return t('bad.min').replace('{min}', String(field.minimum));
  }
  if (state.rangeOverflow) {
    return t('bad.max').replace('{max}', String(field.maximum));
  }
  if (state.tooShort) {
    return t('bad.short').replace('{n}', String(field.min_length));
  }
  if (state.tooLong) {
    return t('bad.long').replace('{n}', String(field.max_length));
  }
  if (state.badInput) {
    return t('bad.shape');
  }
  return state.valueMissing ? t('bad.missing') : node.validationMessage;
}

export function describeLimits(field) {
  const low = field.minimum !== null && field.minimum !== undefined;
  const high = field.maximum !== null && field.maximum !== undefined;
  if (low && high) {
    return t('limit.range').replace('{min}', field.minimum).replace('{max}', field.maximum);
  }
  if (low) {
    return t('limit.min').replace('{min}', field.minimum);
  }
  if (high) {
    return t('limit.max').replace('{max}', field.maximum);
  }
  if (field.min_length && field.min_length === field.max_length) {
    return t('limit.exact').replace('{n}', field.min_length);
  }
  if (field.max_length) {
    return t('limit.length').replace('{n}', field.max_length);
  }
  return '';
}

function control(field) {
  const caption = element('span', { className: 'field-name', textContent: words(field.name) });
  if (field.required) {
    caption.append(element('span', { className: 'required', textContent: ` ${t('field.required')}` }));
  }

  const files = field.kind === 'file' || field.kind === 'files';
  const chooser = files ? fileControl(field) : null;
  const node = chooser ? chooser.node : input(field);
  node.dataset.field = field.name;
  node.dataset.kind = field.kind;
  node.dataset.whole = String(field.step === 1);

  const wrap = element('label', { className: field.kind === 'flag' ? 'field checkbox' : 'field' });
  if (chooser) {
    wrap.append(caption, node, chooser.box);
  } else if (field.kind === 'flag') {
    const line = element('span', { className: 'checkbox-line' });
    line.append(node, caption);
    wrap.append(line);
  } else {
    wrap.append(caption, node);
  }

  const problem = element('span', { className: 'field-problem' });
  node.addEventListener('input', () => {
    const reason = problemFor(node, field);
    problem.textContent = reason;
    wrap.classList.toggle('missing', Boolean(reason));
  });
  wrap.append(problem);

  const limits = describeLimits(field);
  if (limits) {
    wrap.append(element('span', { className: 'field-help quiet', textContent: limits }));
  }

  const help = t(`field.${field.name}`);
  if (help) {
    wrap.append(element('span', { className: 'field-help', textContent: help }));
  }
  if (files && field.accepts) {
    wrap.append(element('span', {
      className: 'field-help quiet',
      textContent: t('field.accepts').replace('{list}', field.accepts.replace(/,/g, ', ')),
    }));
  }
  return wrap;
}

async function valueOf(node) {
  const kind = node.dataset.kind;
  if (kind === 'file') {
    const file = node.files && node.files[0];
    return file ? await encodeFile(file) : undefined;
  }
  if (kind === 'files') {
    const many = await Promise.all(Array.from(node.files || [], encodeFile));
    return many.length ? many : undefined;
  }
  if (kind === 'flag') {
    return node.checked;
  }
  return typed(kind, node.value, node.dataset.whole === 'true');
}

export function typed(kind, raw, whole) {
  if (raw === '') {
    return undefined;
  }
  const numeric = kind === 'number' || (kind === 'choice' && whole);
  return numeric ? Number(raw) : raw;
}

function firstChosenName(panel) {
  const source = Array.from(panel.querySelectorAll('[data-kind=file], [data-kind=files]'))
    .find((node) => node.files && node.files.length);
  return source ? source.files[0].name : '';
}

async function collect(panel, form) {
  const nodes = Array.from(panel.querySelectorAll('[data-field]'));
  const values = await Promise.all(nodes.map(valueOf));
  const given = Object.fromEntries(
    nodes
      .map((node, index) => [node.dataset.field, values[index]])
      .filter(([, value]) => value !== undefined),
  );
  const derived = form.fields.filter((field) => field.kind === 'auto');
  const chosen = derived.length ? firstChosenName(panel) : '';
  return derived.reduce(
    (body, field) => ({ ...body, [field.name]: named(chosen, field.default) }),
    given,
  );
}

export function named(chosen, fallback) {
  const wanted = String(fallback || '');
  if (!chosen) {
    return wanted;
  }
  const suffix = wanted.slice(wanted.lastIndexOf('.'));
  if (!suffix || suffix === wanted || chosen.endsWith(suffix)) {
    return chosen;
  }
  const dot = chosen.lastIndexOf('.');
  return (dot > 0 ? chosen.slice(0, dot) : chosen) + suffix;
}

function blank(node) {
  return node.dataset.kind === 'file' || node.dataset.kind === 'files'
    ? !(node.files && node.files.length)
    : node.value === '';
}

function invalid(panel, form) {
  const byName = new Map(form.fields.map((field) => [field.name, field]));
  return Array.from(panel.querySelectorAll('[data-field]'))
    .filter((node) => typeof node.checkValidity === 'function' && !node.checkValidity())
    .map((node) => {
      const field = byName.get(node.dataset.field) || {};
      return `${words(node.dataset.field)}: ${problemFor(node, field)}`;
    });
}

function missing(panel, form) {
  const required = new Set(
    form.fields.filter((field) => field.required && field.kind !== 'auto').map((field) => field.name),
  );
  return Array.from(panel.querySelectorAll('[data-field]'))
    .filter((node) => required.has(node.dataset.field))
    .filter((node) => {
      const empty = blank(node);
      node.closest('label').classList.toggle('missing', empty);
      return empty;
    })
    .map((node) => words(node.dataset.field));
}

function heading(form) {
  const head = element('div', { className: 'panel-head' });
  head.append(
    element('h2', { className: 'command-name', textContent: form.command }),
    element('span', { className: 'route', textContent: form.method + ' ' + form.route }),
  );
  return head;
}

function summaryOf(form) {
  return label(`summary.${form.command}`, form.summary);
}

function hardwareNotice(form) {
  const notice = element('p', { className: 'banner busy', textContent: t('hardware.checking') });
  call('/api/hardware', 'GET')
    .then((state) => {
      notice.className = `banner ${state.connected ? 'good' : 'bad'}`;
      notice.textContent = state.connected
        ? `${t('hardware.present')} ${state.detail}`
        : `${t('hardware.absent')} ${state.detail}`;
    })
    .catch((error) => {
      notice.className = 'banner bad';
      notice.textContent = `${t('hardware.unknown')} ${error.message}`;
    });
  return notice;
}

function runner(host, form, out) {
  const run = element('button', { type: 'button', className: 'run', textContent: t('button.run') });
  run.addEventListener('click', async () => {
    const empty = missing(host, form);
    if (empty.length) {
      out.replaceChildren(banner('bad', t('state.missing').replace('{fields}', empty.join(', '))));
      return;
    }
    const broken = invalid(host, form);
    if (broken.length) {
      out.replaceChildren(
        banner('bad', t('state.invalid')),
        ...broken.map((reason) => element('p', { className: 'reason', textContent: reason })),
      );
      return;
    }
    run.disabled = true;
    run.textContent = t('state.running');
    out.replaceChildren(banner('busy', t('state.running')));
    try {
      renderResult(out, await call(form.route, form.method, await collect(host, form)));
    } catch (error) {
      out.replaceChildren(
        banner('bad', t('state.failed')),
        element('p', { className: 'reason', textContent: error.message }),
        element('p', { className: 'quiet', textContent: t('state.hint') }),
      );
    } finally {
      run.disabled = false;
      run.textContent = t('button.run');
    }
  });
  return run;
}

function renderPanel() {
  const host = document.getElementById('panel');
  host.replaceChildren();
  const form = selected();
  if (!form) {
    host.append(element('p', { className: 'summary', textContent: t('panel.none') }));
    return;
  }
  host.dataset.command = form.command;

  const out = element('div', { className: 'output' });
  out.append(emptyResult(form));

  const left = element('div', { className: 'fields' });
  left.append(element('p', { className: 'group-label', textContent: t('group.inputs') }));
  const shownFields = form.fields.filter((field) => field.kind !== 'auto');
  left.append(...(shownFields.length
    ? shownFields.map(control)
    : [element('p', { className: 'field-help', textContent: t('group.nothing') })]));
  left.append(runner(host, form, out));

  const right = element('div', { className: 'result' });
  right.append(element('p', { className: 'group-label', textContent: t('group.result') }), out);

  const columns = element('div', { className: 'columns' });
  columns.append(left, right);

  host.append(
    heading(form),
    element('p', { className: 'summary', textContent: summaryOf(form) }),
    ...(form.needs_hardware ? [hardwareNotice(form)] : []),
    columns,
  );
}

function familyButton(family) {
  const button = element('button', { type: 'button', textContent: t(`family.${family}`) });
  button.dataset.family = family;
  button.setAttribute('aria-pressed', String(family === state.family));
  button.addEventListener('click', () => {
    const first = state.forms.find((form) => form.family === family);
    update({ family, filter: '', command: first ? first.command : '' });
    document.getElementById('search').value = '';
    remember();
    render();
  });
  return button;
}

function commandItem(form) {
  const button = element('button', { type: 'button' });
  button.append(
    element('span', { className: 'item-name', textContent: form.command }),
    element('span', { className: 'item-summary', textContent: summaryOf(form) }),
  );
  button.setAttribute('aria-current', String(form.command === state.command));
  button.addEventListener('click', () => {
    update({ command: form.command, family: form.family });
    remember();
    render();
  });
  const item = element('li', {});
  item.append(button);
  return item;
}

function remember() {
  try {
    window.history.replaceState(null, '', '#' + state.command);
  } catch (error) {
    return;
  }
}

function render() {
  document.getElementById('families').replaceChildren(...families().map(familyButton));

  const shown = visible();
  const listHost = document.getElementById('commands');
  listHost.replaceChildren(...(shown.length
    ? shown.map(commandItem)
    : [element('li', { className: 'no-match', textContent: t('list.none') })]));

  renderPanel();
}

function show(wanted) {
  const form = state.forms.find((entry) => entry.command === wanted) || state.forms[0];
  if (form) {
    update({ command: form.command, family: form.family });
  }
}

function wire() {
  document.querySelectorAll('[data-language]').forEach((button) => {
    button.addEventListener('click', () => {
      update({ language: button.dataset.language });
      rememberLanguage(state.language);
      applyLanguage();
    });
  });

  const search = document.getElementById('search');
  search.addEventListener('input', () => {
    update({ filter: search.value });
    const first = visible()[0];
    if (first) {
      update({ command: first.command, family: first.family });
    }
    render();
  });

  window.addEventListener('hashchange', () => {
    show(window.location.hash.replace('#', ''));
    render();
  });
}

export async function start() {
  wire();
  applyLanguage();
  try {
    const catalogue = await call('/api/catalogue', 'GET');
    update({ forms: catalogue.forms });
    show(window.location.hash.replace('#', ''));
    render();
  } catch (error) {
    document.getElementById('panel').replaceChildren(
      banner('bad', t('state.failed')),
      element('p', { className: 'reason', textContent: error.message }),
    );
  }
}
