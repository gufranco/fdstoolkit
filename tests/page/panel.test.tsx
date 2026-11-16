import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Panel } from '../../web/src/panel';
import type { Job } from '../../web/src/schemas';
import { fileStems, gameNames, seeded } from './fakes';
import { choose, fieldOf, FORMS, formOf, reply, serve, settle, withClient } from './harness';

const FAKE = seeded('panel.test');
const [GAME = ''] = gameNames(FAKE, 1);
const [STEM = ''] = fileStems(FAKE, 1);
const INFO = FORMS[0]!;
const BLANK = FORMS[2]!;
const STATUS = FORMS[3]!;
const DUMP = FORMS[4]!;
const WRITE = FORMS[5]!;
const OK = 200;
const CONFLICT = 409;
const NOT_FOUND = 404;

const JOB: Job = {
  id: 'j1',
  command: 'write',
  writes: true,
  stoppable: false,
  stopping: false,
  state: 'running',
  steps: [],
  prompt: '',
  result: null,
  error: '',
  kept: null,
};

function field(container: HTMLElement, name: string): HTMLInputElement {
  return container.querySelector<HTMLInputElement>(`[data-field="${name}"]`)!;
}

async function run(container: HTMLElement): Promise<void> {
  fireEvent.click(container.querySelector('button.run')!);
  await settle();
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Panel', () => {
  it('names the command, its route and what it needs before anything runs', () => {
    // Arrange
    serve();

    // Act
    const { container } = render(withClient(<Panel form={INFO} />));

    // Assert
    expect(container.querySelector('.command-name')!.textContent).toBe('info');
    expect(container.querySelector('.route')!.textContent).toBe('POST /api/info');
    expect(container.querySelector('.summary')!.textContent).toBe('Read a disk.');
    expect(screen.getByText('Fill in data, then press the button.').className).toBe('quiet');
    expect(container.querySelector('button.run')!.textContent).toBe('Measure');
  });

  it('says when a command needs nothing from the visitor', () => {
    // Arrange
    serve();

    // Act
    render(withClient(<Panel form={STATUS} />));

    // Assert
    expect(screen.getByText('This command needs nothing from you. Press the button.').className).toBe('field-help');
    expect(screen.queryByText(/Fill in/)).toBeNull();
  });

  it('refuses to run with a required field empty and marks it', async () => {
    // Arrange
    const sent = serve();
    const { container } = render(withClient(<Panel form={INFO} />));

    // Act
    await run(container);

    // Assert
    expect(container.querySelector('.output .banner')!.textContent).toBe('Still needed: data');
    expect(field(container, 'data').closest('label')!.className).toBe('field missing');
    expect(sent().filter((entry) => entry.key === 'POST /api/info')).toEqual([]);
  });

  it('clears the mark once the missing file is chosen', async () => {
    // Arrange
    serve();
    const { container } = render(withClient(<Panel form={INFO} />));
    await run(container);

    // Act
    await choose(field(container, 'data'), [new File([new Uint8Array([1])], `${STEM}.fds`)]);

    // Assert
    expect(field(container, 'data').closest('label')!.className).toBe('field');
  });

  it('refuses to run with a value out of range', async () => {
    // Arrange
    serve();
    const { container } = render(withClient(<Panel form={BLANK} />));
    fireEvent.change(field(container, 'game_name'), { target: { value: GAME } });
    fireEvent.change(field(container, 'passes'), { target: { value: '0' } });

    // Act
    await run(container);

    // Assert
    expect(container.querySelector('.output .banner')!.textContent).toBe('Some values are out of range.');
    expect(container.querySelector('.output .reason')!.textContent).toBe('passes: Must be 1 or more.');
  });

  it('sends typed values and shows the answer', async () => {
    // Arrange
    const sent = serve({ 'POST /api/blank': () => reply(OK, { headline: 'made a blank disk', ok: true }) });
    const { container } = render(withClient(<Panel form={BLANK} />));
    fireEvent.change(field(container, 'game_name'), { target: { value: GAME } });

    // Act
    await run(container);

    // Assert
    const call = sent().find((entry) => entry.key === 'POST /api/blank');
    expect(call?.body).toEqual({ sides: 1, passes: 1, formatted: true, game_name: GAME });
    expect(container.querySelector('.output .banner')!.textContent).toBe('made a blank disk');
    expect((container.querySelector('button.run') as HTMLButtonElement).disabled).toBe(false);
  });

  it('reports a refusal with the reason and a hint', async () => {
    // Arrange
    serve({ 'POST /api/blank': () => reply(CONFLICT, { detail: [{ loc: ['body', 'game_name'], msg: 'too long' }] }) });
    const { container } = render(withClient(<Panel form={BLANK} />));
    fireEvent.change(field(container, 'game_name'), { target: { value: GAME } });

    // Act
    await run(container);

    // Assert
    expect(container.querySelector('.output .reason')!.textContent).toBe('game name: too long');
    expect(container.querySelector('.output .quiet')!.textContent).toMatch(/^Check that the file/);
  });

  it('runs a GET command without a body', async () => {
    // Arrange
    const sent = serve({ 'GET /api/status': () => reply(OK, { healthy: true }) });
    const { container } = render(withClient(<Panel form={STATUS} />));

    // Act
    await run(container);

    // Assert
    expect(sent().filter((entry) => entry.key === 'GET /api/status')).toEqual([{ key: 'GET /api/status', body: undefined }]);
  });

  it('writes nothing when the erase is cancelled', async () => {
    // Arrange
    const sent = serve();
    const { container } = render(withClient(<Panel form={WRITE} />));
    await choose(field(container, 'data'), [new File([new Uint8Array([1])], `${STEM}.fds`)]);
    await run(container);

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    await settle();

    // Assert
    expect(container.querySelector('.output .banner')!.textContent).toBe('Cancelled. Nothing was written.');
    expect(sent().filter((entry) => entry.key === 'POST /api/jobs/write')).toEqual([]);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('confirms the erase in the request once the dialog agrees, then follows the job', async () => {
    // Arrange
    const sent = serve({
      'POST /api/jobs/write': () => reply(OK, JOB),
      'GET /api/jobs/j1': () => reply(OK, JOB),
    });
    const { container } = render(withClient(<Panel form={WRITE} />));
    await choose(field(container, 'data'), [new File([new Uint8Array([1])], `${STEM}.fds`)]);
    await run(container);

    // Act
    fireEvent.click(screen.getByRole('button', { name: 'Erase and continue' }));
    await settle();

    // Assert
    expect(sent().find((entry) => entry.key === 'POST /api/jobs/write')?.body).toEqual({ data: 'AQ==', confirm: true });
    expect(container.querySelector('.output .banner')!.textContent).toBe('Working on the disk. Each step appears below as it happens.');
  });

  it('starts a job that erases nothing without asking', async () => {
    // Arrange
    const dumping = { ...JOB, command: 'dump', writes: false };
    const sent = serve({ 'POST /api/jobs/dump': () => reply(OK, dumping), 'GET /api/jobs/j1': () => reply(OK, dumping) });
    const { container } = render(withClient(<Panel form={DUMP} />));

    // Act
    await run(container);

    // Assert
    expect(sent().find((entry) => entry.key === 'POST /api/jobs/dump')?.body).toEqual({ sides: 1 });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('picks up a job that was already running', () => {
    // Arrange
    serve({ 'GET /api/jobs/j1': () => reply(OK, JOB) });

    // Act
    const { container } = render(withClient(<Panel form={WRITE} resumed={JOB} />));

    // Assert
    expect(container.querySelector('.output .banner')!.textContent).toBe('A disk operation was already running, so this page picked it up.');
  });

  it('says whether the stick is connected, with the detail as a sentence', async () => {
    // Arrange
    serve();

    // Act
    render(withClient(<Panel form={DUMP} />));
    await settle();

    // Assert
    const notice = screen.getByRole('status');
    expect(notice.className).toBe('banner bad');
    expect(notice.textContent).toBe('No FDSStick is connected, so this command cannot reach a real drive. None connected at 16D0:0AAA');
  });

  it('says so when the stick is connected', async () => {
    // Arrange
    serve({ 'GET /api/hardware': () => reply(OK, { connected: true, detail: 'firmware 3.12' }) });

    // Act
    render(withClient(<Panel form={DUMP} />));
    await settle();

    // Assert
    expect(screen.getByRole('status').textContent).toBe('An FDSStick is connected. Firmware 3.12');
  });

  it('says when the device state could not be read', async () => {
    // Arrange
    serve({ 'GET /api/hardware': () => reply(NOT_FOUND, { detail: 'gone' }) });

    // Act
    render(withClient(<Panel form={DUMP} />));
    await settle();

    // Assert
    expect(screen.getByRole('status').textContent).toBe('The device state could not be read: Gone');
  });

  it('shows the check while the device is being looked for', () => {
    // Arrange
    serve();

    // Act
    render(withClient(<Panel form={formOf({ command: 'probe', family: 'hardware', needs_hardware: true, fields: [fieldOf({ name: 'side', kind: 'number' })] })} />));

    // Assert
    expect(screen.getByRole('status').className).toBe('banner busy');
  });
});
