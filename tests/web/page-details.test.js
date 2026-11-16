import { describe, expect, it, vi } from 'vitest';

import { sentence } from '../../src/fdstoolkit/ui/static/app.js';
import { problemFor } from '../../src/fdstoolkit/ui/static/fields.js';
import { initialLanguage, rememberLanguage } from '../../src/fdstoolkit/ui/static/i18n.js';
import { renderResult } from '../../src/fdstoolkit/ui/static/render.js';
import { field, useHarness } from './harness.js';

useHarness();

describe('problemFor', () => {
  const limits = { minimum: 1, maximum: 20, min_length: 3, max_length: 3 };

  function failing(validity) {
    return { checkValidity: () => false, validity, validationMessage: 'the browser says no' };
  }

  it('says nothing for a valid value or a node with no validation', () => {
    // Arrange
    const expected = '';

    // Act
    const result = problemFor({ checkValidity: () => true }, limits);

    // Assert
    expect(result).toBe(expected);
    expect(problemFor({}, limits)).toBe('');
  });

  it('names every kind of problem in the page language', () => {
    // Arrange
    const expected = 'Needs at least 3 characters.';

    // Act
    const result = problemFor(failing({ tooShort: true }), limits);

    // Assert
    expect(result).toBe(expected);
    expect(problemFor(failing({ tooLong: true }), limits)).toBe('No more than 3 characters.');
    expect(problemFor(failing({ badInput: true }), limits)).toBe('That is not the shape this field expects.');
    expect(problemFor(failing({ valueMissing: true }), limits)).toBe('This one is required.');
    expect(problemFor(failing({}), limits)).toBe('the browser says no');
  });
});

describe('sentence', () => {
  it('capitalises the first letter and leaves the rest alone', () => {
    // Arrange
    const expected = 'None connected at 16D0:0AAA';

    // Act
    const result = sentence('none connected at 16D0:0AAA');

    // Assert
    expect(result).toBe(expected);
    expect(sentence('')).toBe('');
  });
});

describe('the rest of the result layouts', () => {
  it('lists a change that carries no marks, only its two values', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { changes: [{ left: 'A', right: 'B', moved: false }] });

    // Assert
    expect(target.querySelector('.change-marks')).toBeNull();
    expect(target.querySelector('.change-values').textContent).toContain('A');
  });

  it('shows the notes an export carries next to its file', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { name: 'dump.fds', data: 'AQ==', size: 1, notes: ['[FDS016] lost'] });

    // Assert
    expect(target.querySelector('.download').getAttribute('download')).toBe('dump.fds');
    expect(target.querySelector('.download-notes .banner.warn').textContent).toBe('[FDS016] lost');
  });

  it('lays out a list that mixes values and records as pairs', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { mixed: [1, { side: 0 }] });

    // Assert
    expect(target.querySelector('dl dl')).not.toBeNull();
  });

  it('offers a file on its own when nothing else came with it', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { headline: '', file: { name: 'before.fds', data: 'AA==', size: 1 } });

    // Assert
    expect(target.querySelector('a').download).toBe('before.fds');
    expect(target.querySelector('dl')).toBeNull();
  });
});

describe('initialLanguage', () => {
  it('keeps a remembered language the page carries', () => {
    // Arrange
    window.localStorage.setItem('fdstoolkit.language', 'ja');

    // Act
    const language = initialLanguage();

    // Assert
    expect(language).toBe('ja');
    window.localStorage.removeItem('fdstoolkit.language');
  });

  it('follows the browser when nothing is remembered', () => {
    // Arrange
    const expected = 'ja';

    // Act
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('ja-JP');

    // Assert
    expect(initialLanguage()).toBe(expected);
  });

  it('falls back to English for a browser language it does not carry, or none', () => {
    // Arrange
    const language = vi.spyOn(navigator, 'language', 'get');
    const answers = ['pt-BR', ''];

    // Act
    const chosen = answers.map((answer) => {
      language.mockReturnValue(answer);
      return initialLanguage();
    });

    // Assert
    expect(chosen).toEqual(['en', 'en']);
  });

  it('works when storage is blocked', () => {
    // Arrange
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError');
    });
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'QuotaExceededError');
    });

    // Act
    rememberLanguage('ja');

    // Assert
    expect(initialLanguage()).toBe('en');
  });

  it('lets a fault that is not a browser refusal surface', () => {
    // Arrange
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new TypeError('broken');
    });

    // Act
    const remembering = () => rememberLanguage('ja');

    // Assert
    expect(remembering).toThrow(TypeError);
  });

  it('lets a fault reading the stored language surface', () => {
    // Arrange
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new TypeError('broken');
    });

    // Act
    const choosing = () => initialLanguage();

    // Assert
    expect(choosing).toThrow(TypeError);
  });
});
