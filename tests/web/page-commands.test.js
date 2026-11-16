import { describe, expect, it, vi } from 'vitest';

import { choose, field, open, panel, reply, run, sent, settle, useHarness } from './harness.js';

useHarness();

describe('running a command', () => {
  it('refuses to run with a required field empty', async () => {
    // Arrange
    await open('info');

    // Act
    await run();

    // Assert
    expect(panel().querySelector('.output .banner').textContent).toBe('Still needed: data');
    expect(sent.filter((entry) => entry.key === 'POST /api/info')).toEqual([]);
  });

  it('refuses to run with a value out of range', async () => {
    // Arrange
    await open('blank');
    field('game_name').value = 'SMB';
    const node = field('passes');
    node.checkValidity = () => false;
    Object.defineProperty(node, 'validity', { value: { rangeUnderflow: true }, configurable: true });

    // Act
    await run();

    // Assert
    expect(panel().querySelector('.output .reason').textContent).toBe('passes: Must be 1 or more.');
  });

  it('sends typed values and shows the answer', async () => {
    // Arrange
    await open('blank', { 'POST /api/blank': () => reply(200, { headline: 'made a blank disk', ok: true }) });
    field('game_name').value = 'SMB';
    field('sides').value = '2';
    field('ratio').value = '';
    await run();

    // Act
    const call = sent.find((entry) => entry.key === 'POST /api/blank');

    // Assert
    expect(call.body).toEqual({ sides: 2, passes: 1, formatted: true, game_name: 'SMB' });
    expect(panel().querySelector('.output .banner').textContent).toBe('made a blank disk');
    expect(panel().querySelector('button.run').disabled).toBe(false);
  });

  it('encodes the chosen file and derives the output name from it', async () => {
    // Arrange
    await open('info', { 'POST /api/info': () => reply(200, { text: 'Game name: SMB' }) });
    choose(field('data'), [new File([new Uint8Array([1, 2])], 'smb.qd')]);
    await run();

    // Act
    const call = sent.find((entry) => entry.key === 'POST /api/info');

    // Assert
    expect(call.body).toEqual({ data: 'AQI=', name: 'smb.fds' });
  });

  it('sends every file of a many-file field', async () => {
    // Arrange
    await open('consensus', { 'POST /api/consensus': () => reply(200, { headline: 'merged' }) });
    choose(field('images'), [new File([new Uint8Array([1])], 'a.fds'), new File([new Uint8Array([2])], 'b.fds')]);
    await run();

    // Act
    const call = sent.find((entry) => entry.key === 'POST /api/consensus');

    // Assert
    expect(call.body).toEqual({ images: ['AQ==', 'Ag=='] });
  });

  it('leaves out optional files nobody chose and keeps the default name', async () => {
    // Arrange
    await open('lint', { 'POST /api/lint': () => reply(200, { headline: 'clean', ok: true }) });
    await run();

    // Act
    const call = sent.find((entry) => entry.key === 'POST /api/lint');

    // Assert
    expect(call.body).toEqual({ report: 'report.json' });
  });

  it('uses GET for a command that reads only', async () => {
    // Arrange
    await open('status', { 'GET /api/status': () => reply(200, { headline: 'healthy', ok: true }) });

    // Act
    await run();

    // Assert
    expect(panel().querySelector('.output .banner').textContent).toBe('healthy');
  });

  it('says the server failed when its answer is not a result', async () => {
    // Arrange
    await open('status', { 'GET /api/status': () => ({ ok: false, status: 500, json: async () => JSON.parse('Internal Server Error') }) });

    // Act
    await run();

    // Assert
    expect(panel().querySelector('.output .reason').textContent).toBe(
      'The server answered 500 with something that is not a result. Its terminal shows what went wrong.',
    );
  });

  it('reports a refusal with the reason and a hint', async () => {
    // Arrange
    await open('blank', { 'POST /api/blank': () => reply(422, { detail: [{ loc: ['body', 'game_name'], msg: 'too long' }] }) });
    field('game_name').value = 'SMB';

    // Act
    await run();

    // Assert
    expect(panel().querySelector('.output .reason').textContent).toBe('game name: too long');
  });
});

describe('the drive commands', () => {
  const done = {
    id: 'j1',
    command: 'dump',
    writes: false,
    state: 'done',
    steps: [],
    prompt: '',
    result: { name: 'dump.fds', data: 'AA==', size: 1, grade: 'clean' },
    error: '',
  };

  it('says whether the stick is connected, with the detail as a sentence', async () => {
    // Arrange
    const expected =
      'No FDSStick is connected, so this command cannot reach a real drive. None connected at 16D0:0AAA';

    // Act
    await open('dump');

    // Assert
    expect(panel().querySelector('.banner.bad').textContent).toBe(expected);
  });

  it('says when the stick is connected', async () => {
    // Arrange
    const expected = 'An FDSStick is connected. 1 device(s) connected';

    // Act
    await open('dump', { 'GET /api/hardware': () => reply(200, { connected: true, detail: '1 device(s) connected' }) });

    // Assert
    expect(panel().querySelector('.banner.good').textContent).toBe(expected);
  });

  it('says when the stick state cannot be read', async () => {
    // Arrange
    const expected = 'The device state could not be read: Hid failed';

    // Act
    await open('dump', { 'GET /api/hardware': () => reply(500, { detail: 'hid failed' }) });

    // Assert
    expect(panel().querySelector('.banner.bad').textContent).toBe(expected);
  });

  it('runs a dump as a job with no erase dialog', async () => {
    // Arrange
    await open('dump', { 'POST /api/jobs/dump': () => reply(200, done) });

    // Act
    await run();

    // Assert
    expect(document.querySelector('dialog')).toBeNull();
    expect(panel().querySelector('.output a').download).toBe('dump.fds');
  });

  it('writes nothing when the erase is cancelled', async () => {
    // Arrange
    await open('write');
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);
    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .plain').click();

    // Act
    await settle();

    // Assert
    expect(panel().querySelector('.output .banner').textContent).toBe('Cancelled. Nothing was written.');
    expect(sent.filter((entry) => entry.key === 'POST /api/jobs/write')).toEqual([]);
  });

  it('confirms the erase in the request once the dialog agrees', async () => {
    // Arrange
    const written = { ...done, command: 'write', writes: true, result: { headline: 'written', ok: true } };
    await open('write', { 'POST /api/jobs/write': () => reply(200, written) });
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);
    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .danger').click();
    await settle();

    // Act
    const call = sent.find((entry) => entry.key === 'POST /api/jobs/write');

    // Assert
    expect(call.body).toEqual({ data: 'AQ==', confirm: true });
    expect(panel().querySelector('.output .banner').textContent).toBe('written');
  });

  it('shows a failed answer to the turn prompt without losing the job', async () => {
    // Arrange
    const waiting = { ...done, state: 'waiting', prompt: 'turn the disk over', result: null };
    const failed = { ...waiting, state: 'failed', prompt: '', error: 'declined' };
    let polls = 0;
    await open('dump', {
      'POST /api/jobs/dump': () => reply(200, waiting),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? failed : waiting);
      },
      'POST /api/jobs/j1/answer': () => reply(409, { detail: 'that job is not waiting for an answer' }),
    });
    await run();

    // Act
    panel().querySelector('.turn .plain').click();

    // Assert
    await settle();
    expect(panel().querySelector('.output').textContent).toContain('that job is not waiting for an answer');
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('declined'), {
      timeout: 3000,
    });
  });

  it('stops a job that can stop and reports a stop the server refused', async () => {
    // Arrange
    const measuring = { ...done, state: 'running', stoppable: true, result: null };
    let polls = 0;
    await open('dump', {
      'POST /api/jobs/dump': () => reply(200, measuring),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? { ...measuring, state: 'failed', error: 'stopped' } : measuring);
      },
      'POST /api/jobs/j1/stop': () => reply(409, { detail: 'that job cannot be stopped' }),
    });
    await run();

    // Act
    panel().querySelector('.job .dialog-actions .plain').click();

    // Assert
    await settle();
    expect(sent.some((entry) => entry.key === 'POST /api/jobs/j1/stop')).toBe(true);
    expect(panel().querySelector('.output').textContent).toContain('that job cannot be stopped');
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('stopped'), {
      timeout: 3000,
    });
  });

  it('asks before the page closes while a job writes', async () => {
    // Arrange
    const writing = { ...done, command: 'write', writes: true, state: 'running', result: null };
    let polls = 0;
    await open('write', {
      'POST /api/jobs/write': () => reply(200, writing),
      'GET /api/jobs/j1': () => {
        polls += 1;
        return reply(200, polls > 1 ? { ...writing, state: 'failed', error: 'stalled' } : writing);
      },
    });
    choose(field('data'), [new File([new Uint8Array([1])], 'game.fds')]);
    panel().querySelector('button.run').click();
    await settle();
    document.querySelector('dialog .danger').click();
    await settle();
    const leaving = new Event('beforeunload', { cancelable: true });

    // Act
    window.dispatchEvent(leaving);

    // Assert
    expect(leaving.defaultPrevented).toBe(true);
    await vi.waitFor(() => expect(panel().querySelector('.output .reason').textContent).toBe('stalled'), {
      timeout: 3000,
    });
  });

  it('picks up a job that is already running', async () => {
    // Arrange
    const expected = 'dump';

    // Act
    await open('info', { 'GET /api/jobs/current': () => reply(200, { job: done }) });

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe(expected);
    expect(panel().querySelector('.output a').download).toBe('dump.fds');
  });

  it('ignores a running job for a command the page does not offer', async () => {
    // Arrange
    const expected = 'info';

    // Act
    await open('info', { 'GET /api/jobs/current': () => reply(200, { job: { ...done, command: 'gone' } }) });

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe(expected);
  });
});
