import { afterEach, describe, expect, it, vi } from 'vitest';
import { z } from 'zod';

import { call, explain, messageOf } from '../../web/src/api';
import { translate } from '../../web/src/i18n';
import { HardwareSchema } from '../../web/src/schemas';

const english = (key: string): string => translate('en', key);
const OK = 200;
const CONFLICT = 409;
const SERVER_ERROR = 500;

function answer(status: number, body: string): Response {
  return new Response(body, { status, headers: { 'content-type': 'application/json' } });
}

function serve(status: number, body: string): ReturnType<typeof vi.fn> {
  const fetcher = vi.fn(() => Promise.resolve(answer(status, body)));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('explain', () => {
  it('passes a plain message through', () => {
    // Arrange
    const expected = 'that image is not a disk';

    // Act
    const result = explain('that image is not a disk');

    // Assert
    expect(result).toBe(expected);
  });

  it('names the field each validation error came from and joins them', () => {
    // Arrange
    const detail = [
      { loc: ['body', 'bad_blocks'], msg: 'Input should be greater than 0' },
      { loc: ['body', 'passes'], msg: 'too small' },
    ];

    // Act
    const result = explain(detail);

    // Assert
    expect(result).toBe('bad blocks: Input should be greater than 0. passes: too small');
  });

  it('keeps a message that names no field and drops an entry with no message', () => {
    // Arrange
    const detail = [{ msg: 'unreadable' }, 'odd'];

    // Act
    const result = explain(detail);

    // Assert
    expect(result).toBe('unreadable');
  });

  it('falls back to the raw object when the shape is unknown', () => {
    // Arrange
    const expected = '{"odd":true}';

    // Act
    const result = explain({ odd: true });

    // Assert
    expect(result).toBe(expected);
  });
});

describe('call', () => {
  it('reads a GET answer through its schema', async () => {
    // Arrange
    const fetcher = serve(OK, JSON.stringify({ connected: true, detail: 'ready' }));

    // Act
    const result = await call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, english);

    // Assert
    expect(result).toEqual({ connected: true, detail: 'ready' });
    expect(fetcher).toHaveBeenCalledWith('/api/hardware', { method: 'GET', headers: {} });
  });

  it('sends a POST body as JSON', async () => {
    // Arrange
    const fetcher = serve(OK, JSON.stringify({ yes: true }));
    const body = { yes: true };

    // Act
    await call(z.object({ yes: z.boolean() }), { path: '/api/x', method: 'POST', body }, english);

    // Assert
    expect(fetcher).toHaveBeenCalledWith('/api/x', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{"yes":true}',
    });
  });

  it('raises the reason the server gave for a refusal', async () => {
    // Arrange
    serve(CONFLICT, JSON.stringify({ detail: 'the drive is busy' }));

    // Act
    const calling = call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, english);

    // Assert
    await expect(calling).rejects.toThrow('the drive is busy');
  });

  it('raises a refusal that carries no detail field as it came', async () => {
    // Arrange
    serve(CONFLICT, JSON.stringify('the stick is held by another program'));

    // Act
    const calling = call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, english);

    // Assert
    await expect(calling).rejects.toThrow('the stick is held by another program');
  });

  it('says the server answered with something that is not a result', async () => {
    // Arrange
    serve(SERVER_ERROR, 'Internal Server Error');

    // Act
    const calling = call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, english);

    // Assert
    await expect(calling).rejects.toThrow('The server answered 500 with something that is not a result.');
  });

  it('refuses an answer in a shape the page does not read', async () => {
    // Arrange
    serve(OK, JSON.stringify({ connected: 'yes' }));

    // Act
    const calling = call(HardwareSchema, { path: '/api/hardware', method: 'GET' }, english);

    // Assert
    await expect(calling).rejects.toThrow('The server answered /api/hardware in a shape this page does not read');
  });
});

describe('messageOf', () => {
  it('reads the message of an error and prints anything else', () => {
    // Arrange
    const errors: unknown[] = [new Error('the stick went away'), 'plain words'];

    // Act
    const result = errors.map(messageOf);

    // Assert
    expect(result).toEqual(['the stick went away', 'plain words']);
  });
});
