import { DICTIONARIES, FALLBACK, initialLanguage } from './i18n.js';

export let state = {
  language: initialLanguage(),
  forms: [],
  order: [],
  filter: '',
  family: '',
  command: '',
};

export function update(changes) {
  state = { ...state, ...changes };
}

export function t(key) {
  const table = DICTIONARIES[state.language] || DICTIONARIES[FALLBACK];
  return table[key] || '';
}

export function label(key, fallback) {
  return t(key) || fallback;
}

