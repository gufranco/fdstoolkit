import type { CommandForm } from './schemas';
import { orderFamilies } from './values';

export interface Selection {
  readonly filter: string;
  readonly family: string;
  readonly command: string;
}

export type SelectionAction =
  | { readonly type: 'show'; readonly wanted: string; readonly forms: readonly CommandForm[] }
  | { readonly type: 'family'; readonly first: CommandForm }
  | { readonly type: 'command'; readonly form: CommandForm }
  | { readonly type: 'filter'; readonly text: string; readonly forms: readonly CommandForm[] };

export const NOTHING_SELECTED: Selection = { filter: '', family: '', command: '' };

export function familiesOf(forms: readonly CommandForm[], order: readonly string[]): string[] {
  return orderFamilies([...new Set(forms.map((form) => form.family))], order);
}

export function visible(selection: Selection, forms: readonly CommandForm[]): CommandForm[] {
  const needle = selection.filter.trim().toLowerCase();
  if (needle) {
    return forms.filter((form) => form.command.includes(needle));
  }
  return forms.filter((form) => form.family === selection.family);
}

export function selectedForm(
  selection: Selection,
  forms: readonly CommandForm[],
): CommandForm | undefined {
  return forms.find((form) => form.command === selection.command);
}

function pointedAt(selection: Selection, form: CommandForm | undefined): Selection {
  return form ? { ...selection, command: form.command, family: form.family } : selection;
}

export function select(selection: Selection, action: SelectionAction): Selection {
  switch (action.type) {
    case 'show':
      return pointedAt(
        selection,
        action.forms.find((form) => form.command === action.wanted) ?? action.forms[0],
      );
    case 'family':
      return { filter: '', family: action.first.family, command: action.first.command };
    case 'command':
      return pointedAt(selection, action.form);
    case 'filter': {
      const next = { ...selection, filter: action.text };
      return pointedAt(next, visible(next, action.forms)[0]);
    }
  }
}
