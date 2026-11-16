import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LANGUAGE_KEY } from '../../web/src/i18n';
import { Page } from '../../web/src/Page';
import { reply, serve, settle, withClient } from './harness';

const OK = 200;
const SERVER_ERROR = 500;

async function open(hash: string): Promise<HTMLElement> {
  window.history.replaceState(null, '', `#${hash}`);
  const { container } = render(withClient(<Page />));
  await settle();
  return container;
}

function panelCommand(container: HTMLElement): string | null | undefined {
  return container.querySelector('#panel .command-name')?.textContent;
}

beforeEach(() => {
  window.localStorage.setItem(LANGUAGE_KEY, 'en');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('Page', () => {
  it('opens the command the address names, with the families in catalogue order', async () => {
    // Arrange
    serve();

    // Act
    const container = await open('blank');

    // Assert
    expect(panelCommand(container)).toBe('blank');
    expect(container.querySelector('#panel')!.getAttribute('data-command')).toBe('blank');
    const families = [...container.querySelectorAll('#families button')].map((node) => node.textContent);
    expect(families).toEqual(['Inspect', 'Repair', 'Container', 'Hardware', 'Check', 'elsewhere']);
    expect(container.querySelector('[data-family="container"]')!.getAttribute('aria-pressed')).toBe('true');
    expect(container.querySelector('#panel .route')!.textContent).toBe('POST /api/blank');
  });

  it('moves to a family and its first command', async () => {
    // Arrange
    serve();
    const container = await open('blank');

    // Act
    fireEvent.click(container.querySelector('[data-family="hardware"]')!);

    // Assert
    expect(panelCommand(container)).toBe('status');
    expect(window.location.hash).toBe('#status');
  });

  it('picks a command from the list', async () => {
    // Arrange
    serve();
    const container = await open('status');

    // Act
    fireEvent.click(screen.getByRole('button', { name: /^dump/ }));

    // Assert
    expect(panelCommand(container)).toBe('dump');
    expect(screen.getByRole('button', { name: /^dump/ }).getAttribute('aria-current')).toBe('true');
  });

  it('filters the commands by name and says when none match', async () => {
    // Arrange
    serve();
    const container = await open('info');
    const search = container.querySelector<HTMLInputElement>('#search')!;

    // Act
    fireEvent.change(search, { target: { value: 'zz' } });

    // Assert
    expect(container.querySelector('#commands .no-match')!.textContent).toBe('No command matches that.');
    fireEvent.change(search, { target: { value: 'wri' } });
    expect(panelCommand(container)).toBe('write');
  });

  it('follows the address when it changes', async () => {
    // Arrange
    serve();
    const container = await open('info');

    // Act
    window.location.hash = '#consensus';
    fireEvent(window, new HashChangeEvent('hashchange'));
    await settle();

    // Assert
    expect(panelCommand(container)).toBe('consensus');
  });

  it('switches language, remembers it and marks the page', async () => {
    // Arrange
    serve();
    const container = await open('info');

    // Act
    fireEvent.click(container.querySelector('[data-language="ja"]')!);

    // Assert
    expect(document.documentElement.lang).toBe('ja');
    expect(window.localStorage.getItem(LANGUAGE_KEY)).toBe('ja');
    expect(container.querySelector('[data-language="ja"]')!.getAttribute('aria-pressed')).toBe('true');
    expect(container.querySelector('#search')!.getAttribute('placeholder')).toBe('コマンドを絞り込む');
  });

  it('reports a catalogue it could not read', async () => {
    // Arrange
    serve({ 'GET /api/catalogue': () => reply(SERVER_ERROR, { detail: 'the server is restarting' }) });

    // Act
    const container = await open('info');

    // Assert
    expect(container.querySelector('#panel .reason')!.textContent).toBe('the server is restarting');
  });

  it('asks the visitor to choose while the catalogue is on its way', () => {
    // Arrange
    serve();

    // Act
    const { container } = render(withClient(<Page />));

    // Assert
    expect(container.querySelector('#panel .summary')!.textContent).toBe('Choose a command on the left.');
  });

  it('picks up a job that is already running', async () => {
    // Arrange
    const job = {
      id: 'j1',
      command: 'dump',
      writes: false,
      stoppable: false,
      stopping: false,
      state: 'running',
      steps: [],
      prompt: '',
      result: null,
      error: '',
      kept: null,
    };
    serve({ 'GET /api/jobs/current': () => reply(OK, { job }), 'GET /api/jobs/j1': () => reply(OK, job) });

    // Act
    const container = await open('info');

    // Assert
    expect(panelCommand(container)).toBe('dump');
    expect(container.querySelector('#panel .output .banner')!.textContent).toBe('A disk operation was already running, so this page picked it up.');
  });

  it('ignores a running job for a command the page does not offer', async () => {
    // Arrange
    serve({ 'GET /api/jobs/current': () => reply(OK, { job: { id: 'j9', command: 'gone', writes: false, stoppable: false, stopping: false, state: 'running', steps: [], prompt: '', result: null, error: '', kept: null } }) });

    // Act
    const container = await open('info');

    // Assert
    expect(panelCommand(container)).toBe('info');
  });

  it('keeps working when the browser refuses to change the address', async () => {
    // Arrange
    serve();
    const container = await open('status');
    vi.spyOn(window.history, 'replaceState').mockImplementationOnce(() => {
      throw new DOMException('too many calls', 'SecurityError');
    });

    // Act
    fireEvent.click(screen.getByRole('button', { name: /^dump/ }));

    // Assert
    expect(panelCommand(container)).toBe('dump');
  });
});
