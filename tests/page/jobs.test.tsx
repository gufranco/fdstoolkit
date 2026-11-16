import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { EraseDialog, erases, isJobRoute, JobFollower, JobView } from '../../web/src/jobs';
import type { Job } from '../../web/src/schemas';
import { fileStems, seeded } from './fakes';
import { fieldOf, formOf, reply, serve, settle, withClient } from './harness';

const FAKE = seeded('jobs.test');
const [STEM = ''] = fileStems(FAKE, 1);
const FAST = 1;
const SERVER_ERROR = 500;

const RUNNING: Job = {
  id: 'j1',
  command: 'dump',
  writes: false,
  stoppable: false,
  stopping: false,
  state: 'running',
  steps: ['reading side 0'],
  prompt: '',
  result: null,
  error: '',
  kept: null,
};

function noAnswer(): void {
  return undefined;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  cleanup();
});

describe('routes', () => {
  it('tells a job route and an erasing command', () => {
    // Arrange
    const routes = ['/api/jobs/dump', '/api/info'];
    const confirmField = fieldOf({ name: 'confirm', kind: 'flag', hidden: true });
    const write = formOf({ command: 'write', family: 'hardware', fields: [confirmField] });
    const erase = formOf({ command: 'erase', family: 'hardware', fields: [confirmField] });
    const dump = formOf({ command: 'dump', family: 'hardware', fields: [fieldOf({ name: 'confirm', kind: 'flag' })] });

    // Act
    const result = [...routes.map(isJobRoute), erases(write), erases(erase), erases(dump)];

    // Assert
    expect(result).toEqual([true, false, true, true, false]);
  });
});

describe('EraseDialog', () => {
  it('opens as a modal labelled by its title and starts on cancel', () => {
    // Arrange
    const answer = vi.fn();

    // Act
    render(<EraseDialog command="write" onAnswer={answer} />);

    // Assert
    const dialog = screen.getByRole('dialog', { name: 'This erases the disk in the drive' });
    expect(dialog.hasAttribute('open')).toBe(true);
    expect(document.activeElement?.textContent).toBe('Cancel');
    expect(screen.getByText(/Writing replaces everything/).id).toBe('erase-body');
  });

  it('answers no on cancel, on escape, and yes on erase', () => {
    // Arrange
    const answer = vi.fn();
    render(<EraseDialog command="surface" onAnswer={answer} />);

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }));
    fireEvent.click(screen.getByRole('button', { name: 'Erase and continue' }));

    // Assert
    expect(answer.mock.calls).toEqual([[false], [false], [true]]);
  });
});

describe('JobView', () => {
  it('lists the steps in the command line language and says what is happening', () => {
    // Arrange
    const job = { ...RUNNING, writes: true };

    // Act
    const { container } = render(<JobView job={job} onAnswer={noAnswer} onStop={noAnswer} />);

    // Assert
    expect(container.querySelector('.banner')!.className).toBe('banner busy');
    expect(container.querySelector('ol.steps')!.getAttribute('lang')).toBe('en');
    expect(container.querySelector('ol.steps')!.getAttribute('aria-live')).toBe('polite');
    expect(screen.getByText(/Keep this page open/).className).toBe('quiet');
  });

  it('offers a stop while a stoppable job runs, and disables it once pressed', () => {
    // Arrange
    const stop = vi.fn();
    render(<JobView job={{ ...RUNNING, stoppable: true }} onAnswer={noAnswer} onStop={stop} />);
    const button = screen.getByRole('button', { name: 'Stop' });

    // Act
    fireEvent.click(button);

    // Assert
    expect(stop).toHaveBeenCalledTimes(1);
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it('says a stop is under way instead of offering another', () => {
    // Arrange
    const job = { ...RUNNING, stoppable: true, stopping: true };

    // Act
    render(<JobView job={job} onAnswer={noAnswer} onStop={noAnswer} />);

    // Assert
    expect(screen.getByText('Stopping after the read in progress.').className).toBe('quiet');
  });

  it('asks the operator to turn the disk and takes one answer', () => {
    // Arrange
    const answer = vi.fn();
    const job = { ...RUNNING, state: 'waiting' as const, prompt: 'turn the disk over' };
    render(<JobView job={job} onAnswer={answer} onStop={noAnswer} />);

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'The disk is turned over' }));

    // Assert
    expect(answer).toHaveBeenCalledWith(true);
    expect(screen.getByRole('alert').querySelector('.prompt')!.getAttribute('lang')).toBe('en');
    expect((screen.getByRole('button', { name: 'Stop' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('asks a calibration to step the adjustment, and lets the operator stop', () => {
    // Arrange
    const answer = vi.fn();
    const job = { ...RUNNING, command: 'calibrate', state: 'waiting' as const, prompt: 'step once' };
    render(<JobView job={job} onAnswer={answer} onStop={noAnswer} />);

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));

    // Assert
    expect(answer).toHaveBeenCalledWith(false);
    expect(screen.getByRole('button', { name: 'Turned it, read again' })).toBeDefined();
  });

  it('gives the reason a job failed and the disk read before it', () => {
    // Arrange
    const kept = { name: `${STEM}.fds`, data: 'AQ==', size: 1 };
    const job = { ...RUNNING, writes: true, state: 'failed' as const, error: 'refused', kept };

    // Act
    const { container } = render(<JobView job={job} onAnswer={noAnswer} onStop={noAnswer} />);

    // Assert
    expect(container.querySelector('.reason')!.textContent).toBe('refused');
    expect(container.querySelector('.download')!.getAttribute('download')).toBe(`${STEM}.fds`);
    expect(screen.queryByText(/Keep this page open/)).toBeNull();
  });

  it('offers nothing extra when a failed job kept no file', () => {
    // Arrange
    const job = { ...RUNNING, state: 'failed' as const, error: 'refused' };

    // Act
    const { container } = render(<JobView job={job} onAnswer={noAnswer} onStop={noAnswer} />);

    // Assert
    expect(container.querySelector('.download')).toBeNull();
  });
});

describe('JobFollower', () => {
  it('shows the result of a job that already finished without asking again', () => {
    // Arrange
    const sent = serve();
    const done = { ...RUNNING, state: 'done' as const, result: { headline: 'grade clean', ok: true } };

    // Act
    const { container } = render(withClient(<JobFollower first={done} />));

    // Assert
    expect(container.querySelector('.banner')!.textContent).toBe('grade clean');
    expect(sent()).toEqual([]);
  });

  it('follows a job to its result', async () => {
    // Arrange
    const done = { ...RUNNING, state: 'done', result: { headline: 'grade clean', ok: true } };
    serve({ 'GET /api/jobs/j1': () => reply(200, done) });

    // Act
    const { container } = render(withClient(<JobFollower first={RUNNING} pollMs={FAST} />));
    await settle();

    // Assert
    expect(container.querySelector('.banner')!.textContent).toBe('grade clean');
  });

  it('sends the answer and the stop the operator gives', async () => {
    // Arrange
    const waiting = { ...RUNNING, state: 'waiting' as const, prompt: 'turn it', stoppable: true };
    const sent = serve({
      'GET /api/jobs/j1': () => reply(200, waiting),
      'POST /api/jobs/j1/answer': () => reply(200, { ok: true }),
    });
    render(withClient(<JobFollower first={waiting} pollMs={FAST} />));

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'The disk is turned over' }));
    await settle();

    // Assert
    expect(sent().filter((entry) => entry.key === 'POST /api/jobs/j1/answer')).toEqual([
      { key: 'POST /api/jobs/j1/answer', body: { yes: true } },
    ]);
  });

  it('shows why an answer or a stop did not reach the server', async () => {
    // Arrange
    const stoppable = { ...RUNNING, stoppable: true };
    serve({ 'GET /api/jobs/j1': () => reply(200, stoppable) });
    render(withClient(<JobFollower first={stoppable} pollMs={FAST} />));

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await settle();

    // Assert
    expect(screen.getByText('no route POST /api/jobs/j1/stop').className).toBe('banner bad');
  });

  it('reports a job it can no longer read', async () => {
    // Arrange
    serve({ 'GET /api/jobs/j1': () => reply(SERVER_ERROR, { detail: 'the board was cleared' }) });

    // Act
    const { container } = render(withClient(<JobFollower first={RUNNING} pollMs={FAST} />));
    await settle();

    // Assert
    expect(container.querySelector('.reason')!.textContent).toBe('the board was cleared');
  });

  it('stops following after its poll limit', async () => {
    // Arrange
    serve({ 'GET /api/jobs/j1': () => reply(200, RUNNING) });

    // Act
    const { container } = render(withClient(<JobFollower first={RUNNING} pollMs={FAST} polls={2} />));
    await waitFor(() => {
      expect(container.querySelector('.banner')!.className).toBe('banner warn');
    });

    // Assert
    expect(container.querySelector('.banner')!.textContent).toMatch(/^Stopped following the operation/);
  });

  it('asks before the page closes while a write runs, and no longer once it ends', async () => {
    // Arrange
    const writing = { ...RUNNING, writes: true };
    const failed = { ...writing, state: 'failed' as const, error: 'stalled' };
    serve({ 'GET /api/jobs/j1': () => reply(200, failed) });
    render(withClient(<JobFollower first={writing} pollMs={50} />));
    const during = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(during);

    // Act
    await waitFor(() => {
      expect(screen.getByText('stalled').className).toBe('reason');
    });

    // Assert
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect([during.defaultPrevented, after.defaultPrevented]).toEqual([true, false]);
  });
});
