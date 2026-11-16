import { createContext, useContext } from 'react';

import { FALLBACK, translate } from './i18n';
import type { Translate } from './values';

export const LanguageContext = createContext<Translate>((key) => translate(FALLBACK, key));

export function useT(): Translate {
  return useContext(LanguageContext);
}
