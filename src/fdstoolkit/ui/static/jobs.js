import { call } from './api.js';
import { banner, element } from './dom.js';
import { download, isDownload, renderResult } from './render.js';
import { t } from './state.js';

const POLL_MS = 500;
const POLL_LIMIT = 7200;
const ERASING = new Set(['write', 'surface']);

function pause(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export function isJobRoute(route) {
  return route.startsWith('/api/jobs/');
}

export function confirmErase(command) {
  return new Promise((resolve) => {
    const dialog = element('dialog', { className: 'erase' });
    dialog.setAttribute('aria-labelledby', 'erase-title');
    dialog.setAttribute('aria-describedby', 'erase-body');
    const cancel = element('button', { type: 'button', className: 'plain', textContent: t('confirm.cancel') });
    const go = element('button', { type: 'button', className: 'danger', textContent: t('confirm.go') });
    const actions = element('div', { className: 'dialog-actions' });
    actions.append(cancel, go);
    dialog.append(
      element('h2', { id: 'erase-title', textContent: t('confirm.title') }),
      element('p', { id: 'erase-body', textContent: t(`confirm.${command}`) }),
      actions,
    );
    const finish = (answer) => {
      dialog.close();
      dialog.remove();
      resolve(answer);
    };
    cancel.addEventListener('click', () => finish(false));
    go.addEventListener('click', () => finish(true));
    dialog.addEventListener('cancel', (event) => {
      event.preventDefault();
      finish(false);
    });
    document.body.append(dialog);
    dialog.showModal();
    cancel.focus();
  });
}

function turnPrompt(job, answer) {
  const box = element('div', { className: 'turn' });
  box.setAttribute('role', 'alert');
  const done = job.command === 'calibrate' ? 'job.stepped' : 'job.turned';
  const yes = element('button', { type: 'button', className: 'run', textContent: t(done) });
  const no = element('button', { type: 'button', className: 'plain', textContent: t('job.stop') });
  const reply = (given) => {
    yes.disabled = true;
    no.disabled = true;
    answer(job.id, given);
  };
  yes.addEventListener('click', () => reply(true));
  no.addEventListener('click', () => reply(false));
  const actions = element('div', { className: 'dialog-actions' });
  actions.append(no, yes);
  box.append(element('p', { className: 'prompt', lang: COMMAND_LANGUAGE, textContent: job.prompt }), actions);
  return box;
}

const JOB_BANNER = { running: 'busy', waiting: 'warn', failed: 'bad', done: 'good' };
const COMMAND_LANGUAGE = 'en';

function stopControl(job, stop) {
  if (job.stopping) {
    return element('p', { className: 'quiet', textContent: t('job.stopping') });
  }
  const button = element('button', { type: 'button', className: 'plain', textContent: t('job.stop') });
  button.addEventListener('click', () => {
    button.disabled = true;
    stop(job.id);
  });
  const actions = element('div', { className: 'dialog-actions' });
  actions.append(button);
  return actions;
}

export function jobView(job, answer, stop) {
  const box = element('div', { className: 'job' });
  box.append(banner(JOB_BANNER[job.state], t(`job.${job.state}`)));
  if (job.writes && job.state !== 'failed') {
    box.append(element('p', { className: 'quiet', textContent: t('job.keep') }));
  }
  box.append(element('p', { className: 'output-language', textContent: t('job.output') }));
  const steps = element('ol', { className: 'steps', lang: COMMAND_LANGUAGE });
  steps.setAttribute('aria-live', 'polite');
  steps.append(...job.steps.map((step) => element('li', { textContent: step })));
  box.append(steps);
  if (job.state === 'waiting') {
    box.append(turnPrompt(job, answer));
  }
  if (job.stoppable && job.state === 'running') {
    box.append(stopControl(job, stop));
  }
  if (job.state === 'failed') {
    box.append(element('p', { className: 'reason', lang: COMMAND_LANGUAGE, textContent: job.error }));
  }
  if (job.state === 'failed' && isDownload(job.kept)) {
    box.append(download(job.kept));
  }
  return box;
}

function keepPageOpen(event) {
  event.preventDefault();
}

export async function follow(
  first,
  out,
  { fetchJob = (id) => call(`/api/jobs/${id}`, 'GET'), polls = POLL_LIMIT } = {},
) {
  const answer = (id, yes) =>
    call(`/api/jobs/${id}/answer`, 'POST', { yes }).catch((error) => {
      out.append(banner('bad', error.message));
    });
  const stop = (id) =>
    call(`/api/jobs/${id}/stop`, 'POST', {}).catch((error) => {
      out.append(banner('bad', error.message));
    });
  if (first.writes) {
    window.addEventListener('beforeunload', keepPageOpen);
  }
  let job = first;
  let shown = '';
  try {
    for (let poll = 0; poll < polls; poll += 1) {
      if (job.state === 'done') {
        renderResult(out, job.result);
        return job;
      }
      const seen = JSON.stringify(job);
      if (seen !== shown) {
        out.replaceChildren(jobView(job, answer, stop));
        shown = seen;
      }
      if (job.state === 'failed') {
        return job;
      }
      await pause(POLL_MS);
      job = await fetchJob(job.id);
    }
    out.replaceChildren(banner('warn', t('job.lost')));
    return job;
  } finally {
    window.removeEventListener('beforeunload', keepPageOpen);
  }
}

export async function startJob(form, out, body) {
  const erasing = ERASING.has(form.command);
  if (erasing && !(await confirmErase(form.command))) {
    out.replaceChildren(banner('warn', t('state.cancelled')));
    return;
  }
  const job = await call(form.route, 'POST', erasing ? { ...body, confirm: true } : body);
  await follow(job, out);
}

