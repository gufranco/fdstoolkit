import { type ReactElement, type ReactNode, useId, useState } from 'react';

import { useT } from './language';
import type { CommandForm, FormField } from './schemas';
import { describeLimits, helpFor, named, type Translate, typed, words } from './values';

type Control = HTMLInputElement | HTMLSelectElement;
type Checkable = Pick<Control, 'checkValidity' | 'validity' | 'validationMessage'>;
type Reporter = (problem: string) => void;

const FILE_KINDS: ReadonlySet<string> = new Set(['file', 'files']);

export function problemFor(node: Checkable, field: FormField, t: Translate): string {
  if (node.checkValidity()) {
    return '';
  }
  const state = node.validity;
  if (state.rangeUnderflow) {
    return t('bad.min').replace('{min}', String(field.minimum));
  }
  if (state.rangeOverflow) {
    return t('bad.max').replace('{max}', String(field.maximum));
  }
  if (state.tooShort) {
    return t('bad.short').replace('{n}', String(field.min_length));
  }
  if (state.tooLong) {
    return t('bad.long').replace('{n}', String(field.max_length));
  }
  if (state.badInput) {
    return t('bad.shape');
  }
  return state.valueMissing ? t('bad.missing') : node.validationMessage;
}

function shownDefault(field: FormField): string {
  return field.default === null || field.default === undefined ? '' : String(field.default);
}

function marks(field: FormField): Record<string, string> {
  return { 'data-field': field.name, 'data-kind': field.kind, 'data-whole': String(field.step === 1) };
}

function limits(field: FormField): Record<string, number | boolean | undefined> {
  return {
    min: field.minimum ?? undefined,
    max: field.maximum ?? undefined,
    minLength: field.min_length ?? undefined,
    maxLength: field.max_length ?? undefined,
    required: field.required,
  };
}

interface ControlProps {
  readonly spec: FormField;
  readonly report: Reporter;
  readonly named: Naming;
}

interface Naming {
  readonly labelledBy: string;
  readonly describedBy: string;
}

function Input(props: ControlProps): ReactElement {
  const t = useT();
  const onInput = (event: { currentTarget: Control }): void => {
    props.report(problemFor(event.currentTarget, props.spec, t));
  };
  if (props.spec.kind === 'flag') {
    return (
      <input
        type="checkbox"
        aria-labelledby={props.named.labelledBy}
        aria-describedby={props.named.describedBy}
        defaultChecked={Boolean(props.spec.default)}
        onInput={onInput}
        {...marks(props.spec)}
      />
    );
  }
  if (props.spec.kind === 'choice') {
    return (
      <select
        aria-labelledby={props.named.labelledBy}
        aria-describedby={props.named.describedBy}
        defaultValue={shownDefault(props.spec)}
        onInput={onInput}
        {...marks(props.spec)}
      >
        {props.spec.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  const numeric = props.spec.kind === 'number';
  const step = numeric ? { step: props.spec.step === null ? 'any' : String(props.spec.step) } : {};
  return (
    <input
      type={numeric ? 'number' : 'text'}
      aria-labelledby={props.named.labelledBy}
      aria-describedby={props.named.describedBy}
      defaultValue={shownDefault(props.spec)}
      onInput={onInput}
      {...step}
      {...limits(props.spec)}
      {...marks(props.spec)}
    />
  );
}

export function chosenFiles(node: Pick<HTMLInputElement, 'files'>): File[] {
  return Array.from(node.files ?? []);
}

interface ChooserProps extends ControlProps {
  readonly onChosen: () => void;
}

function FileChooser(props: ChooserProps): ReactElement {
  const t = useT();
  const [names, setNames] = useState('');
  const onChange = (event: { currentTarget: HTMLInputElement }): void => {
    setNames(chosenFiles(event.currentTarget).map((file) => file.name).join(', '));
    props.report(problemFor(event.currentTarget, props.spec, t));
    props.onChosen();
  };
  return (
    <>
      <input
        type="file"
        aria-labelledby={props.named.labelledBy}
        aria-describedby={props.named.describedBy}
        multiple={props.spec.kind === 'files'}
        className="offscreen"
        accept={props.spec.accepts}
        required={props.spec.required}
        onChange={onChange}
        {...marks(props.spec)}
      />
      <span className="file-box">
        <span className="file-button">{t(props.spec.kind === 'files' ? 'file.many' : 'file.one')}</span>
        <span className="file-name">{names || t('file.none')}</span>
      </span>
    </>
  );
}

interface HelpProps {
  readonly spec: FormField;
  readonly command: string;
  readonly id: string;
}

function HelpLines(props: HelpProps): ReactElement {
  const t = useT();
  const bounds = describeLimits(props.spec, t);
  const help = helpFor(props.command, props.spec, t);
  const accepts = FILE_KINDS.has(props.spec.kind) && props.spec.accepts
    ? t('field.accepts').replace('{list}', props.spec.accepts.replaceAll(',', ', '))
    : '';
  return (
    <span className="field-helps" id={props.id}>
      {bounds ? <span className="field-help quiet">{bounds}</span> : null}
      {help ? <span className="field-help">{help}</span> : null}
      {accepts ? <span className="field-help quiet">{accepts}</span> : null}
    </span>
  );
}

function Caption(props: { readonly spec: FormField; readonly id: string }): ReactElement {
  const t = useT();
  return (
    <span className="field-name" id={props.id}>
      {words(props.spec.name)}
      {props.spec.required ? <span className="required"> {t('field.required')}</span> : null}
    </span>
  );
}

function arranged(flag: boolean, caption: ReactNode, control: ReactNode): ReactNode {
  if (flag) {
    return (
      <span className="checkbox-line">
        {control}
        {caption}
      </span>
    );
  }
  return (
    <>
      {caption}
      {control}
    </>
  );
}

export interface FieldControlProps {
  readonly spec: FormField;
  readonly command: string;
  readonly missing: boolean;
  readonly onEdited: (name: string) => void;
}

export function FieldControl(props: FieldControlProps): ReactElement {
  const [problem, setProblem] = useState('');
  const base = useId();
  const named: Naming = { labelledBy: `${base}-name`, describedBy: `${base}-problem ${base}-help` };
  const chosen = (): void => {
    props.onEdited(props.spec.name);
  };
  const control = FILE_KINDS.has(props.spec.kind)
    ? <FileChooser spec={props.spec} report={setProblem} named={named} onChosen={chosen} />
    : <Input spec={props.spec} report={setProblem} named={named} />;
  const flag = props.spec.kind === 'flag';
  const kind = flag ? 'field checkbox' : 'field';
  return (
    <label className={props.missing || problem ? `${kind} missing` : kind}>
      {arranged(flag, <Caption spec={props.spec} id={`${base}-name`} />, control)}
      <span className="field-problem" id={`${base}-problem`}>{problem}</span>
      <HelpLines spec={props.spec} command={props.command} id={`${base}-help`} />
    </label>
  );
}

function shownFields(form: CommandForm): FormField[] {
  return form.fields.filter((field) => field.kind !== 'auto' && !field.hidden);
}

function controlFor<T extends Control>(host: ParentNode, field: FormField): T {
  const node = host.querySelector<T>(`[data-field="${field.name}"]`);
  if (node === null) {
    throw new Error(`the page lost the control for ${field.name}`);
  }
  return node;
}

async function encoded(file: File): Promise<string> {
  const buffer = new Uint8Array(await file.arrayBuffer());
  return btoa(Array.from(buffer, (byte) => String.fromCharCode(byte)).join(''));
}

async function valueFor(host: ParentNode, field: FormField): Promise<unknown> {
  if (FILE_KINDS.has(field.kind)) {
    const files = await Promise.all(chosenFiles(controlFor<HTMLInputElement>(host, field)).map(encoded));
    if (!files.length) {
      return undefined;
    }
    return field.kind === 'files' ? files : files[0];
  }
  if (field.kind === 'flag') {
    return controlFor<HTMLInputElement>(host, field).checked;
  }
  return typed(field.kind, controlFor(host, field).value, field.step === 1);
}

function firstChosenName(host: ParentNode, form: CommandForm): string {
  const files = shownFields(form)
    .filter((field) => FILE_KINDS.has(field.kind))
    .flatMap((field) => chosenFiles(controlFor<HTMLInputElement>(host, field)));
  return files[0]?.name ?? '';
}

export async function collect(host: ParentNode, form: CommandForm): Promise<Record<string, unknown>> {
  const shown = shownFields(form);
  const values = await Promise.all(shown.map((field) => valueFor(host, field)));
  const given = shown.flatMap((field, index) =>
    values[index] === undefined ? [] : [[field.name, values[index]] as const],
  );
  const chosen = firstChosenName(host, form);
  const derived = form.fields
    .filter((field) => field.kind === 'auto')
    .map((field) => [field.name, named(chosen, field.default)] as const);
  return Object.fromEntries([...given, ...derived]);
}

function blank(host: ParentNode, field: FormField): boolean {
  if (FILE_KINDS.has(field.kind)) {
    return chosenFiles(controlFor<HTMLInputElement>(host, field)).length === 0;
  }
  return controlFor(host, field).value === '';
}

export function missingIn(host: ParentNode, form: CommandForm): string[] {
  return shownFields(form)
    .filter((field) => field.required && blank(host, field))
    .map((field) => field.name);
}

export function invalidIn(host: ParentNode, form: CommandForm, t: Translate): string[] {
  return shownFields(form).flatMap((field) => {
    const node = host.querySelector<Control>(`[data-field="${field.name}"]`);
    if (node === null) {
      return [];
    }
    const problem = problemFor(node, field, t);
    return problem ? [`${words(field.name)}: ${problem}`] : [];
  });
}
