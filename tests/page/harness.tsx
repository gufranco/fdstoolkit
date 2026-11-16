import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from '@testing-library/react';
import type { ReactElement } from 'react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import type { CommandForm, FormField } from '../../web/src/schemas';

type Route = (body: unknown) => Response;

export interface Sent {
  readonly key: string;
  readonly body: unknown;
}

export const OK = 200;
export const NOT_FOUND = 404;

export function fieldOf(overrides: Partial<FormField> & Pick<FormField, 'name' | 'kind'>): FormField {
  return {
    required: false,
    accepts: '',
    default: null,
    options: [],
    minimum: null,
    maximum: null,
    step: null,
    min_length: null,
    max_length: null,
    hidden: false,
    ...overrides,
  };
}

export function formOf(overrides: Partial<CommandForm> & Pick<CommandForm, 'command' | 'family'>): CommandForm {
  return {
    route: `/api/${overrides.command}`,
    method: 'POST',
    summary: '',
    needs_hardware: false,
    fields: [],
    ...overrides,
  };
}

export const FORMS: readonly CommandForm[] = [
  formOf({
    command: 'info',
    family: 'inspect',
    summary: 'Read a disk.',
    fields: [
      fieldOf({ name: 'data', kind: 'file', required: true, accepts: '.fds,.qd' }),
      fieldOf({ name: 'name', kind: 'auto', default: 'disk.fds' }),
    ],
  }),
  formOf({
    command: 'consensus',
    family: 'repair',
    summary: 'Merge reads.',
    fields: [fieldOf({ name: 'images', kind: 'files', required: true })],
  }),
  formOf({
    command: 'blank',
    family: 'container',
    summary: 'Make a blank disk.',
    fields: [
      fieldOf({ name: 'sides', kind: 'choice', options: ['1', '2'], default: 1, step: 1 }),
      fieldOf({ name: 'passes', kind: 'number', minimum: 1, maximum: 20, step: 1, default: 1 }),
      fieldOf({ name: 'ratio', kind: 'number' }),
      fieldOf({ name: 'formatted', kind: 'flag', default: true }),
      fieldOf({ name: 'game_name', kind: 'text', required: true, min_length: 3, max_length: 3 }),
    ],
  }),
  formOf({ command: 'status', family: 'hardware', route: '/api/status', method: 'GET' }),
  formOf({
    command: 'dump',
    family: 'hardware',
    route: '/api/jobs/dump',
    summary: 'Dump a disk.',
    needs_hardware: true,
    fields: [fieldOf({ name: 'sides', kind: 'choice', options: ['1', '2'], default: 1, step: 1 })],
  }),
  formOf({
    command: 'write',
    family: 'hardware',
    route: '/api/jobs/write',
    summary: 'Write a disk.',
    needs_hardware: true,
    fields: [
      fieldOf({ name: 'data', kind: 'file', required: true, accepts: '.fds' }),
      fieldOf({ name: 'confirm', kind: 'flag', hidden: true }),
    ],
  }),
  formOf({
    command: 'lint',
    family: 'check',
    summary: 'Look for problems.',
    fields: [
      fieldOf({ name: 'reference', kind: 'file' }),
      fieldOf({ name: 'others', kind: 'files' }),
      fieldOf({ name: 'report', kind: 'auto', default: 'report.json' }),
    ],
  }),
  formOf({ command: 'oddity', family: 'elsewhere', summary: 'Not translated.' }),
];

export const CATALOGUE = { forms: FORMS, families: ['inspect', 'repair', 'container', 'hardware'] };

export function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

export function serve(extra: Readonly<Record<string, Route>> = {}): () => readonly Sent[] {
  let sent: readonly Sent[] = [];
  const routes: Readonly<Record<string, Route>> = {
    'GET /api/catalogue': () => reply(OK, CATALOGUE),
    'GET /api/jobs/current': () => reply(OK, { job: null }),
    'GET /api/hardware': () => reply(OK, { connected: false, detail: 'none connected at 16D0:0AAA' }),
    ...extra,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, init: RequestInit) => {
      const key = `${init.method ?? 'GET'} ${path}`;
      const body: unknown = typeof init.body === 'string' ? JSON.parse(init.body) : undefined;
      sent = [...sent, { key, body }];
      const route = routes[key];
      return Promise.resolve(route ? route(body) : reply(NOT_FOUND, { detail: `no route ${key}` }));
    }),
  );
  return () => sent;
}

export async function settle(): Promise<void> {
  await act(async () => {
    for (let round = 0; round < 8; round += 1) {
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
    }
  });
}

export async function choose(node: HTMLElement, files: File[]): Promise<void> {
  await userEvent.upload(node, files, { applyAccept: false });
  await settle();
}

export function withClient(ui: ReactElement): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}
