import { element } from './dom.js';
import { words } from './render.js';
import { t } from './state.js';

async function encodeFile(file) {
  const buffer = await file.arrayBuffer();
  return window.btoa(Array.from(new Uint8Array(buffer), (byte) => String.fromCharCode(byte)).join(''));
}

function chosen(node) {
  const files = Array.from(node.files);
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
      textContent: option,
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

function present(value) {
  return value !== null && value !== undefined;
}

export function describeLimits(field) {
  if (present(field.minimum) && present(field.maximum)) {
    return t('limit.range').replace('{min}', field.minimum).replace('{max}', field.maximum);
  }
  const parts = [
    present(field.minimum) ? t('limit.min').replace('{min}', field.minimum) : '',
    present(field.maximum) ? t('limit.max').replace('{max}', field.maximum) : '',
  ].filter(Boolean);
  if (parts.length) {
    return parts.join(' ');
  }
  if (field.min_length && field.min_length === field.max_length) {
    return t('limit.exact').replace('{n}', field.min_length);
  }
  if (field.max_length) {
    return t('limit.length').replace('{n}', field.max_length);
  }
  return '';
}

export function helpFor(command, field) {
  return t(`field.${command}.${field.name}`) || t(`field.${field.name}`);
}

export function control(field, command) {
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

  const help = helpFor(command, field);
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
    const file = node.files[0];
    return file ? await encodeFile(file) : undefined;
  }
  if (kind === 'files') {
    const many = await Promise.all(Array.from(node.files, encodeFile));
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
    .find((node) => node.files.length);
  return source ? source.files[0].name : '';
}

export async function collect(panel, form) {
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
    ? !node.files.length
    : node.value === '';
}

export function invalid(panel, form) {
  const byName = new Map(form.fields.map((field) => [field.name, field]));
  return Array.from(panel.querySelectorAll('[data-field]'))
    .filter((node) => typeof node.checkValidity === 'function' && !node.checkValidity())
    .map((node) => {
      return `${words(node.dataset.field)}: ${problemFor(node, byName.get(node.dataset.field))}`;
    });
}

export function missing(panel, form) {
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

