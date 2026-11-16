import { cleanup, render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';

import { translate } from '../../web/src/i18n';
import { LanguageContext, useT } from '../../web/src/language';

function Cancel(): ReactElement {
  const t = useT();
  return <p>{t('confirm.cancel')}</p>;
}

afterEach(() => {
  cleanup();
});

describe('useT', () => {
  it('speaks English when no language was provided', () => {
    // Arrange
    const expected = 'Cancel';

    // Act
    render(<Cancel />);

    // Assert
    expect(screen.getByText(expected).tagName).toBe('P');
  });

  it('speaks the language the page provides', () => {
    // Arrange
    const japanese = (key: string): string => translate('ja', key);

    // Act
    render(
      <LanguageContext value={japanese}>
        <Cancel />
      </LanguageContext>,
    );

    // Assert
    expect(screen.getByText('キャンセル').tagName).toBe('P');
  });
});
