import { words } from './render.js';
import { t } from './state.js';

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

export async function call(path, method, body) {
  const answer = await fetch(path, {
    method,
    headers: method === 'GET' ? {} : { 'content-type': 'application/json' },
    body: method === 'GET' ? undefined : JSON.stringify(body),
  });
  const payload = await answer.json().catch(() => null);
  if (payload === null) {
    throw new Error(t('state.unreadable').replace('{status}', String(answer.status)));
  }
  if (!answer.ok) {
    throw new Error(explain(payload.detail));
  }
  return payload;
}

