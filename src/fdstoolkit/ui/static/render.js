import { banner, element } from './dom.js';
import { t } from './state.js';

export function words(key) {
  return key.replace(/_/g, ' ');
}

export function bytes(size) {
  const kib = 1024;
  return size < kib ? `${size} B` : `${(size / kib).toFixed(1)} KiB`;
}

export function download(entry) {
  const link = element('a', {
    href: 'data:application/octet-stream;base64,' + entry.data,
    download: entry.name,
    className: 'download',
    textContent: `${t('button.download')} ${entry.name}`,
  });
  const row = element('div', { className: 'download-row' });
  row.append(link, element('span', { className: 'download-size', textContent: bytes(entry.size) }));
  const notes = Array.isArray(entry.notes) ? entry.notes : [];
  if (!notes.length) {
    return row;
  }
  const box = element('div', { className: 'download-notes' });
  box.append(row, ...notes.map((note) => banner('warn', note)));
  return box;
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

function proseOf(value) {
  if (Array.isArray(value)) {
    return value.some(isProse) ? value.map(scalar) : [];
  }
  return isProse(value) ? [scalar(value)] : [];
}

function hasProse(row) {
  return Object.values(row).some((value) => proseOf(value).length > 0);
}

function fill(item, entries) {
  const marks = entries.filter(([, value]) => proseOf(value).length === 0);
  if (marks.length) {
    const head = element('p', { className: 'change-marks' });
    head.append(...marks.map(([key, value]) => chip(key, value)));
    item.append(head);
  }
  entries
    .flatMap(([, value]) => proseOf(value))
    .forEach((text) => {
      item.append(element('p', { className: 'change-note', textContent: text }));
    });
}

function record(row) {
  const item = element('li', { className: 'change' });
  fill(
    item,
    Object.entries(row).filter(([, value]) => !(Array.isArray(value) && value.length === 0)),
  );
  return item;
}

function records(rows) {
  const list = element('ul', { className: 'changes' });
  list.append(...rows.map(record));
  return list;
}

function change(row) {
  const item = element('li', { className: 'change' });
  fill(
    item,
    Object.entries(row)
      .filter(([key]) => key !== 'left' && key !== 'right')
      .filter(([, value]) => value !== false),
  );
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

function rowsOf(rows) {
  return rows.some(hasProse) ? records(rows) : table(rows);
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
      holder.append(isChange(value) ? changes(value) : rowsOf(value));
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

function downloads(target, payload) {
  const extra = Object.values(payload).filter(isDownload);
  target.replaceChildren(banner('good', t('state.file')), download(payload), ...extra.map(download));
}

function withFile(target, payload) {
  const { file, ...rest } = payload;
  const shown = reported(rest);
  const middle = Object.keys(shown).length ? [pairs(shown)] : [];
  target.replaceChildren(verdict(payload), download(file), ...middle);
}

function fileList(target, payload) {
  target.replaceChildren(banner('good', t('state.files').replace('{n}', String(payload.files.length))));
  target.append(...payload.files.map(download));
}

function textReport(target, payload) {
  target.replaceChildren(verdict(payload), element('pre', { textContent: payload.text }));
}

function recordReport(target, payload) {
  const rest = reported(payload);
  const middle = Object.keys(rest).length ? [pairs(rest)] : [];
  target.replaceChildren(verdict(payload), ...middle, raw(payload));
}

function plainValue(target, payload) {
  target.replaceChildren(
    banner('good', t('state.done')),
    element('pre', { textContent: JSON.stringify(payload, null, 2) }),
  );
}

const LAYOUTS = [
  [(payload) => isDownload(payload), downloads],
  [(payload) => payload && isDownload(payload.file), withFile],
  [
    (payload) => payload && Array.isArray(payload.files) && payload.files.length
      && payload.files.every(isDownload),
    fileList,
  ],
  [(payload) => payload && typeof payload.text === 'string', textReport],
  [(payload) => payload && typeof payload === 'object', recordReport],
];

export function renderResult(target, payload) {
  const layout = LAYOUTS.find(([fits]) => fits(payload));
  (layout ? layout[1] : plainValue)(target, payload);
}

