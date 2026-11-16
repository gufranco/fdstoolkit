import type { Download, FormField } from './schemas';

export type Translate = (key: string) => string;

const KIB = 1024;
const PROSE_LENGTH = 24;

export function words(key: string): string {
  return key.replaceAll('_', ' ');
}

export function bytes(size: number): string {
  return size < KIB ? `${size} B` : `${(size / KIB).toFixed(1)} KiB`;
}

export function sentence(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function scalar(value: unknown, t: Translate): string {
  if (value === null || value === undefined) {
    return t('value.none');
  }
  if (typeof value === 'boolean') {
    return t(value ? 'value.yes' : 'value.no');
  }
  return String(value);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isDownload(entry: unknown): entry is Download {
  return (
    isRecord(entry) &&
    typeof entry['data'] === 'string' &&
    typeof entry['size'] === 'number' &&
    typeof entry['name'] === 'string'
  );
}

export function isChange(rows: readonly unknown[]): boolean {
  return rows.every((row) => isRecord(row) && 'left' in row && 'right' in row);
}

export function isProse(value: unknown): boolean {
  return typeof value === 'string' && (value.includes(' ') || value.length > PROSE_LENGTH);
}

export function orderFamilies(present: readonly string[], order: readonly string[]): string[] {
  const known = order.filter((family) => present.includes(family));
  const rest = present.filter((family) => !order.includes(family)).toSorted();
  return [...known, ...rest];
}

export function named(chosen: string, fallback: unknown): string {
  const wanted = typeof fallback === 'string' ? fallback : '';
  if (!chosen) {
    return wanted;
  }
  const suffix = wanted.slice(wanted.lastIndexOf('.'));
  if (!suffix || suffix === wanted || chosen.endsWith(suffix)) {
    return chosen;
  }
  const dot = chosen.lastIndexOf('.');
  return (dot > 0 ? chosen.slice(0, dot) : chosen) + suffix;
}

export function typed(kind: string, raw: string, whole: boolean): string | number | undefined {
  if (raw === '') {
    return undefined;
  }
  const numeric = kind === 'number' || (kind === 'choice' && whole);
  return numeric ? Number(raw) : raw;
}

function present(value: number | null): value is number {
  return value !== null;
}

export function describeLimits(field: FormField, t: Translate): string {
  const { minimum, maximum, min_length: shortest, max_length: longest } = field;
  if (present(minimum) && present(maximum)) {
    return t('limit.range').replace('{min}', String(minimum)).replace('{max}', String(maximum));
  }
  if (present(minimum)) {
    return t('limit.min').replace('{min}', String(minimum));
  }
  if (present(maximum)) {
    return t('limit.max').replace('{max}', String(maximum));
  }
  if (shortest !== null && shortest === longest) {
    return t('limit.exact').replace('{n}', String(shortest));
  }
  return longest === null ? '' : t('limit.length').replace('{n}', String(longest));
}

export function helpFor(command: string, field: FormField, t: Translate): string {
  return t(`field.${command}.${field.name}`) || t(`field.${field.name}`);
}
