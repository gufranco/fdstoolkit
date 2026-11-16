import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  FALLBACK,
  initialLanguage,
  LANGUAGE_KEY,
  rememberLanguage,
  tolerateRefusal,
  translate,
} from '../../web/src/i18n';

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('translate', () => {
  it('translates a key in the language chosen', () => {
    // Arrange
    const expected = 'キャンセル';

    // Act
    const text = translate('ja', 'confirm.cancel');

    // Assert
    expect(text).toBe(expected);
  });

  it('falls back to English for a language it does not carry', () => {
    // Arrange
    const expected = 'Cancel';

    // Act
    const text = translate('xx', 'confirm.cancel');

    // Assert
    expect(text).toBe(expected);
  });

  it('answers nothing for a key with no translation', () => {
    // Arrange
    const key = 'summary.nothing-like-this';

    // Act
    const text = translate(FALLBACK, key);

    // Assert
    expect(text).toBe('');
  });
});

describe('initialLanguage', () => {
  it('prefers the language the visitor chose before', () => {
    // Arrange
    window.localStorage.setItem(LANGUAGE_KEY, 'ja');

    // Act
    const language = initialLanguage();

    // Assert
    expect(language).toBe('ja');
  });

  it('ignores a stored language it does not carry and follows the browser', () => {
    // Arrange
    window.localStorage.setItem(LANGUAGE_KEY, 'xx');
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('ja-JP');

    // Act
    const language = initialLanguage();

    // Assert
    expect(language).toBe('ja');
  });

  it('falls back to English when the browser language is not carried', () => {
    // Arrange
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('pt-BR');

    // Act
    const language = initialLanguage();

    // Assert
    expect(language).toBe(FALLBACK);
  });

  it('falls back to English when the browser names no language', () => {
    // Arrange
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('');

    // Act
    const language = initialLanguage();

    // Assert
    expect(language).toBe(FALLBACK);
  });

  it('still starts when storage refuses to be read', () => {
    // Arrange
    const getItem = vi.spyOn(window.localStorage, 'getItem').mockImplementationOnce(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('ja-JP');

    // Act
    const language = initialLanguage();

    // Assert
    expect(getItem).toHaveBeenCalledTimes(1);
    expect(language).toBe('ja');
  });
});

describe('rememberLanguage', () => {
  it('keeps the choice for the next visit', () => {
    // Arrange
    const code = 'ja';

    // Act
    rememberLanguage(code);

    // Assert
    expect(window.localStorage.getItem(LANGUAGE_KEY)).toBe(code);
  });

  it('carries on when storage refuses the write', () => {
    // Arrange
    const setItem = vi.spyOn(window.localStorage, 'setItem').mockImplementationOnce(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });

    // Act
    rememberLanguage('ja');

    // Assert
    expect(setItem).toHaveBeenCalledTimes(1);
  });
});

describe('tolerateRefusal', () => {
  it('raises anything that is not a browser refusal', () => {
    // Arrange
    const error = new TypeError('broken');

    // Act
    const tolerating = (): void => {
      tolerateRefusal(error);
    };

    // Assert
    expect(tolerating).toThrow(error);
  });
});
