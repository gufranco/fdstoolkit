import { describe, expect, it, vi } from 'vitest';

import { start } from '../../src/fdstoolkit/ui/static/app.js';
import { choose, field, open, panel, reply, useHarness } from './harness.js';
import { fileStems, seeded } from './fakes.js';

const FAKE = seeded('page.test');
const [STEM] = fileStems(FAKE, 1);

useHarness();

describe('start', () => {
  it('opens the command named in the address and orders the families', async () => {
    // Arrange
    const expected = 'blank';

    // Act
    await open('blank');

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe(expected);
    expect([...document.querySelectorAll('#families button')].map((node) => node.dataset.family)).toEqual([
      'inspect',
      'repair',
      'container',
      'hardware',
      'check',
      'elsewhere',
    ]);
  });

  it('opens the first command when the address names none it knows', async () => {
    // Arrange
    const expected = 'info';

    // Act
    await open('missing');

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe(expected);
  });

  it('says what went wrong when the catalogue cannot be read', async () => {
    // Arrange
    const expected = 'the server stopped';

    // Act
    await open('info', { 'GET /api/catalogue': () => reply(500, { detail: 'the server stopped' }) });

    // Assert
    expect(panel().querySelector('.reason').textContent).toBe(expected);
  });

  it('shows an empty page when the catalogue carries no command and no family order', async () => {
    // Arrange
    const expected = 'Choose a command on the left.';

    // Act
    await open('info', { 'GET /api/catalogue': () => reply(200, { forms: [] }) });

    // Assert
    expect(panel().textContent).toBe(expected);
    expect(document.querySelector('#commands .no-match')).not.toBeNull();
  });
});

describe('the command list', () => {
  it('switches to the first command of a family', async () => {
    // Arrange
    await open('info');

    // Act
    document.querySelector('#families [data-family=repair]').click();

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe('consensus');
    expect(window.location.hash).toBe('#consensus');
  });

  it('opens the command clicked in the list', async () => {
    // Arrange
    await open('dump');

    // Act
    document.querySelectorAll('#commands button')[2].click();

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe('write');
  });

  it('filters across families and opens the first match', async () => {
    // Arrange
    await open('info');
    const search = document.getElementById('search');
    search.value = 'wri';

    // Act
    search.dispatchEvent(new Event('input'));

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe('write');
  });

  it('keeps the open command when the filter matches nothing', async () => {
    // Arrange
    await open('info');
    const search = document.getElementById('search');
    search.value = 'nothing-like-this';

    // Act
    search.dispatchEvent(new Event('input'));

    // Assert
    expect(document.querySelector('#commands .no-match').textContent).toBe('No command matches that.');
    expect(panel().querySelector('.command-name').textContent).toBe('info');
  });

  it('follows the address when it changes', async () => {
    // Arrange
    await open('info');
    window.history.replaceState(null, '', '#blank');

    // Act
    window.dispatchEvent(new Event('hashchange'));

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe('blank');
  });

  it('keeps working when the address cannot be rewritten', async () => {
    // Arrange
    await open('info');
    vi.spyOn(window.history, 'replaceState').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });

    // Act
    document.querySelector('#families [data-family=container]').click();

    // Assert
    expect(panel().querySelector('.command-name').textContent).toBe('blank');
  });

  it('falls back to the summary the catalogue carries when no translation exists', async () => {
    // Arrange
    const expected = 'Not translated.';

    // Act
    await open('oddity');

    // Assert
    expect(panel().querySelector('.summary').textContent).toBe(expected);
  });
});

describe('languages', () => {
  it('translates the page and remembers the choice', async () => {
    // Arrange
    await open('info');

    // Act
    document.querySelector('[data-language=ja]').click();

    // Assert
    expect(document.documentElement.lang).toBe('ja');
    expect(document.querySelector('[data-language=ja]').getAttribute('aria-pressed')).toBe('true');
    expect(window.localStorage.getItem('fdstoolkit.language')).toBe('ja');
    document.querySelector('[data-language=en]').click();
  });

  it('falls back to English for a language it does not carry', async () => {
    // Arrange
    await open('info');
    const unknown = document.createElement('button');
    unknown.dataset.language = 'xx';
    document.querySelector('.languages').append(unknown);
    await start();

    // Act
    unknown.click();

    // Assert
    expect(document.querySelector('[data-i18n=title]').textContent).toBe('Famicom Disk System Toolkit');
    document.querySelector('[data-language=en]').click();
  });
});

describe('the form', () => {
  it('builds every kind of control with its limits and help', async () => {
    // Arrange
    const expected = 'SELECT';

    // Act
    await open('blank');

    // Assert
    expect(field('sides').tagName).toBe(expected);
    expect(field('sides').value).toBe('1');
    expect(field('passes').min).toBe('1');
    expect(field('passes').max).toBe('20');
    expect(field('ratio').step).toBe('any');
    expect(field('formatted').checked).toBe(true);
    expect(field('game_name').minLength).toBe(3);
    expect(field('game_name').maxLength).toBe(3);
    expect(field('game_name').required).toBe(true);
    expect(panel().textContent).toContain('Fill in game name, then press the button.');
  });

  it('says a command needs nothing when it has no fields', async () => {
    // Arrange
    const expected = 'This command needs nothing from you. Press the button.';

    // Act
    await open('status');

    // Assert
    expect(panel().textContent).toContain(expected);
  });

  it('names the file chosen and what the field accepts', async () => {
    // Arrange
    await open('info');
    const node = field('data');

    // Act
    choose(node, [new File([new Uint8Array([1])], `${STEM}.fds`)]);

    // Assert
    expect(panel().querySelector('.file-name').textContent).toBe(`${STEM}.fds`);
    expect(panel().textContent).toContain('Expects .fds, .qd');
    choose(node, []);
    expect(panel().querySelector('.file-name').textContent).toBe('No file chosen');
  });

  it('explains a value as soon as it goes out of range', async () => {
    // Arrange
    await open('blank');
    const node = field('passes');
    node.checkValidity = () => false;
    Object.defineProperty(node, 'validity', { value: { rangeOverflow: true }, configurable: true });

    // Act
    node.dispatchEvent(new Event('input'));

    // Assert
    expect(node.closest('label').classList.contains('missing')).toBe(true);
    expect(node.closest('label').querySelector('.field-problem').textContent).toBe('Must be 20 or less.');
  });
});
