import type { z } from 'zod';

import { isRecord, type Translate, words } from './values';

export interface Request {
  readonly path: string;
  readonly method: 'GET' | 'POST';
  readonly body?: unknown;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function issue(item: unknown): string {
  if (!isRecord(item) || typeof item['msg'] !== 'string') {
    return '';
  }
  const location = item['loc'];
  const where = Array.isArray(location) ? location.filter((part) => part !== 'body').join(' ') : '';
  return where ? `${words(where)}: ${item['msg']}` : item['msg'];
}

export function explain(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map(issue).filter(Boolean).join('. ');
  }
  return JSON.stringify(detail);
}

function init(request: Request): RequestInit {
  if (request.method === 'GET') {
    return { method: 'GET', headers: {} };
  }
  return {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(request.body),
  };
}

async function payloadOf(answer: Response): Promise<unknown> {
  try {
    return (await answer.json()) as unknown;
  } catch {
    return null;
  }
}

export async function call<T>(schema: z.ZodType<T>, request: Request, t: Translate): Promise<T> {
  const answer = await fetch(request.path, init(request));
  const payload = await payloadOf(answer);
  if (payload === null) {
    throw new Error(t('state.unreadable').replace('{status}', String(answer.status)));
  }
  if (!answer.ok) {
    throw new Error(explain(isRecord(payload) ? payload['detail'] : payload));
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    const problem = parsed.error.issues.map((entry) => entry.message).join('; ');
    throw new Error(t('state.shape').replace('{path}', request.path).replace('{problem}', problem));
  }
  return parsed.data;
}
