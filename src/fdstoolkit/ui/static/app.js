import { call } from './api.js';
import { banner, element } from './dom.js';
import { collect, control, invalid, missing } from './fields.js';
import { rememberLanguage, tolerateRefusal } from './i18n.js';
import { follow, isJobRoute, startJob } from './jobs.js';
import { renderResult, words } from './render.js';
import { label, state, t, update } from './state.js';

export function orderFamilies(present, order) {
  const known = order.filter((family) => present.includes(family));
  const rest = present.filter((family) => !order.includes(family)).toSorted();
  return [...known, ...rest];
}

function families() {
  return orderFamilies([...new Set(state.forms.map((form) => form.family))], state.order);
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

export function sentence(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function hardwareNotice() {
  const notice = element('p', { className: 'banner busy', textContent: t('hardware.checking') });
  call('/api/hardware', 'GET')
    .then((state) => {
      notice.className = `banner ${state.connected ? 'good' : 'bad'}`;
      notice.textContent = state.connected
        ? `${t('hardware.present')} ${sentence(state.detail)}`
        : `${t('hardware.absent')} ${sentence(state.detail)}`;
    })
    .catch((error) => {
      notice.className = 'banner bad';
      notice.textContent = `${t('hardware.unknown')} ${sentence(error.message)}`;
    });
  return notice;
}

async function resume() {
  const { job } = await call('/api/jobs/current', 'GET');
  if (!job) {
    return;
  }
  const form = state.forms.find((entry) => entry.command === job.command);
  if (!form) {
    return;
  }
  update({ command: form.command, family: form.family });
  render();
  const out = document.querySelector('#panel .output');
  out.replaceChildren(banner('warn', t('job.resumed')));
  await follow(job, out);
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
      const body = await collect(host, form);
      if (isJobRoute(form.route)) {
        await startJob(form, out, body);
      } else {
        renderResult(out, await call(form.route, form.method, body));
      }
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
  const shownFields = form.fields.filter((field) => field.kind !== 'auto' && !field.hidden);
  left.append(...(shownFields.length
    ? shownFields.map((field) => control(field, form.command))
    : [element('p', { className: 'field-help', textContent: t('group.nothing') })]));
  left.append(runner(host, form, out));

  const right = element('div', { className: 'result' });
  right.append(element('p', { className: 'group-label', textContent: t('group.result') }), out);

  const columns = element('div', { className: 'columns' });
  columns.append(left, right);

  host.append(
    heading(form),
    element('p', { className: 'summary', textContent: summaryOf(form) }),
    ...(form.needs_hardware ? [hardwareNotice()] : []),
    columns,
  );
}

function familyButton(family) {
  const button = element('button', { type: 'button', textContent: t(`family.${family}`) });
  button.dataset.family = family;
  button.setAttribute('aria-pressed', String(family === state.family));
  button.addEventListener('click', () => {
    const first = state.forms.find((form) => form.family === family);
    update({ family, filter: '', command: first.command });
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
    tolerateRefusal(error);
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
    update({ forms: catalogue.forms, order: catalogue.families || [] });
    show(window.location.hash.replace('#', ''));
    render();
    await resume();
  } catch (error) {
    document.getElementById('panel').replaceChildren(
      banner('bad', t('state.failed')),
      element('p', { className: 'reason', textContent: error.message }),
    );
  }
}
