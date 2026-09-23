const state = { language: window.i18n.initialLanguage(), forms: [], filter: '' };

function t(key) {
  const table = window.i18n.DICTIONARIES[state.language] || window.i18n.DICTIONARIES[window.i18n.FALLBACK];
  return table[key] || key;
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
  let binary = '';
  new Uint8Array(buffer).forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return window.btoa(binary);
}

async function call(path, method, body) {
  const answer = await fetch(path, {
    method,
    headers: method === 'GET' ? {} : { 'content-type': 'application/json' },
    body: method === 'GET' ? undefined : JSON.stringify(body),
  });
  const payload = await answer.json();
  if (!answer.ok) {
    const detail = payload.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return payload;
}

function download(name, data, size) {
  const link = document.createElement('a');
  link.href = 'data:application/octet-stream;base64,' + data;
  link.download = name;
  link.textContent = t('button.download') + ' ' + name + ' (' + size + ')';
  return link;
}

function renderResult(target, payload) {
  target.textContent = '';
  if (payload && typeof payload.data === 'string' && typeof payload.size === 'number') {
    target.appendChild(download(payload.name, payload.data, payload.size));
    return;
  }
  if (payload && Array.isArray(payload.files)) {
    payload.files.forEach((entry) => {
      const row = document.createElement('div');
      row.appendChild(download(entry.name, entry.data, entry.size));
      target.appendChild(row);
    });
    return;
  }
  if (payload && typeof payload.text === 'string') {
    const block = document.createElement('pre');
    block.textContent = payload.text;
    target.appendChild(block);
    return;
  }
  const block = document.createElement('pre');
  block.textContent = JSON.stringify(payload, null, 2);
  target.appendChild(block);
}

function control(field) {
  const wrap = document.createElement('label');
  const caption = document.createElement('span');
  caption.textContent = field.name.replace(/_/g, ' ') + (field.required ? ' *' : '');
  wrap.appendChild(caption);

  let input;
  if (field.kind === 'file' || field.kind === 'files') {
    input = document.createElement('input');
    input.type = 'file';
    if (field.kind === 'files') {
      input.multiple = true;
    }
  } else if (field.kind === 'flag') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = Boolean(field.default);
  } else if (field.kind === 'number') {
    input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    if (field.default !== null && field.default !== undefined) {
      input.value = String(field.default);
    }
  } else if (field.kind === 'choice') {
    input = document.createElement('select');
    field.options.forEach((option) => {
      const node = document.createElement('option');
      node.value = option;
      node.textContent = option === '' ? t('flux.auto') : option;
      input.appendChild(node);
    });
    if (field.default !== null && field.default !== undefined) {
      input.value = String(field.default);
    }
  } else {
    input = document.createElement('input');
    input.type = 'text';
    if (field.default !== null && field.default !== undefined) {
      input.value = String(field.default);
    }
  }
  input.dataset.field = field.name;
  input.dataset.kind = field.kind;
  wrap.appendChild(input);
  return wrap;
}

async function collect(panel) {
  const body = {};
  const inputs = panel.querySelectorAll('[data-field]');
  for (const input of inputs) {
    const name = input.dataset.field;
    const kind = input.dataset.kind;
    if (kind === 'file') {
      const file = input.files && input.files[0];
      if (file) {
        body[name] = await encodeFile(file);
      }
    } else if (kind === 'files') {
      const many = [];
      for (const file of Array.from(input.files || [])) {
        many.push(await encodeFile(file));
      }
      if (many.length) {
        body[name] = many;
      }
    } else if (kind === 'flag') {
      body[name] = input.checked;
    } else if (kind === 'number') {
      if (input.value !== '') {
        body[name] = Number(input.value);
      }
    } else if (input.value !== '') {
      body[name] = input.value;
    }
  }
  return body;
}

function panelFor(form) {
  const panel = document.createElement('section');
  panel.className = 'command';
  panel.dataset.command = form.command;

  const title = document.createElement('h2');
  title.textContent = form.command;
  panel.appendChild(title);

  const route = document.createElement('p');
  route.className = 'hint';
  route.textContent = form.method + ' ' + form.route;
  panel.appendChild(route);

  form.fields.forEach((field) => panel.appendChild(control(field)));

  const run = document.createElement('button');
  run.type = 'button';
  run.textContent = t('button.run');
  panel.appendChild(run);

  const out = document.createElement('div');
  out.className = 'result';
  out.textContent = t('result.empty');
  panel.appendChild(out);

  run.addEventListener('click', async () => {
    try {
      const body = await collect(panel);
      renderResult(out, await call(form.route, form.method, body));
    } catch (error) {
      out.textContent = t('error.failed') + ' ' + error.message;
    }
  });

  return panel;
}

function render() {
  const host = document.getElementById('commands');
  host.textContent = '';
  const needle = state.filter.trim().toLowerCase();
  state.forms
    .filter((form) => !needle || form.command.includes(needle))
    .forEach((form) => host.appendChild(panelFor(form)));
}

function wire() {
  document.querySelectorAll('[data-language]').forEach((button) => {
    button.addEventListener('click', () => {
      state.language = button.dataset.language;
      window.i18n.rememberLanguage(state.language);
      applyLanguage();
    });
  });

  const search = document.getElementById('search');
  search.addEventListener('input', () => {
    state.filter = search.value;
    render();
  });
}

async function start() {
  wire();
  applyLanguage();
  try {
    const catalogue = await call('/api/catalogue', 'GET');
    state.forms = catalogue.forms;
    render();
  } catch (error) {
    document.getElementById('commands').textContent = t('error.failed') + ' ' + error.message;
  }
}

start();
