import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  chosenFiles,
  collect,
  FieldControl,
  invalidIn,
  missingIn,
  problemFor,
} from '../../web/src/fields';
import { translate } from '../../web/src/i18n';
import type { FormField } from '../../web/src/schemas';
import { fileStems, seeded } from './fakes';
import { choose, fieldOf, FORMS, formOf } from './harness';

const FAKE = seeded('fields.test');
const [STEM = '', OTHER_STEM = ''] = fileStems(FAKE, 2);
const english = (key: string): string => translate('en', key);
const INFO = FORMS[0]!;
const BLANK = FORMS[2]!;
const WRITE = FORMS[5]!;
const LINT = FORMS[6]!;

function host(form = BLANK): HTMLElement {
  const { container } = render(
    <div>
      {form.fields
        .filter((field) => field.kind !== 'auto' && !field.hidden)
        .map((field) => (
          <FieldControl
            key={field.name}
            spec={field}
            command={form.command}
            missing={false}
            onEdited={vi.fn()}
          />
        ))}
    </div>,
  );
  return container;
}

function control(container: HTMLElement, name: string): HTMLInputElement {
  return container.querySelector<HTMLInputElement>(`[data-field="${name}"]`)!;
}

function checkable(validity: Partial<ValidityState>, message = ''): Parameters<typeof problemFor>[0] {
  return {
    checkValidity: () => false,
    validity: { ...validity } as ValidityState,
    validationMessage: message,
  };
}

const BOUNDED: FormField = fieldOf({
  name: 'game_name',
  kind: 'text',
  minimum: 1,
  maximum: 9,
  min_length: 3,
  max_length: 4,
});

afterEach(() => {
  cleanup();
});

describe('FieldControl', () => {
  it('draws every kind of control with its default and limits', () => {
    // Arrange
    const container = host();

    // Act
    const values = ['sides', 'passes', 'ratio', 'formatted', 'game_name'].map((name) => control(container, name));

    // Assert
    expect(values.map((node) => node.tagName)).toEqual(['SELECT', 'INPUT', 'INPUT', 'INPUT', 'INPUT']);
    expect(values[0]!.value).toBe('1');
    expect([values[1]!.min, values[1]!.max, values[1]!.step, values[1]!.value]).toEqual(['1', '20', '1', '1']);
    expect(values[2]!.step).toBe('any');
    expect(values[3]!.checked).toBe(true);
    expect([values[4]!.minLength, values[4]!.maxLength, values[4]!.required]).toEqual([3, 3, true]);
    expect(values[1]!.dataset['whole']).toBe('true');
    expect(screen.getByText('Between 1 and 20.').className).toBe('field-help quiet');
    expect(screen.getByText('Exactly 3 characters.').className).toBe('field-help quiet');
  });

  it('marks a required field and names it in words', () => {
    // Arrange
    const container = host();

    // Act
    const caption = control(container, 'game_name').closest('label')!.querySelector('.field-name')!;

    // Assert
    expect(caption.textContent).toBe('game name (required)');
  });

  it('shows a file chooser with what it accepts and what was chosen', async () => {
    // Arrange
    const container = host(INFO);
    const node = control(container, 'data');

    // Act
    await choose(node, [new File([new Uint8Array([1])], `${STEM}.fds`)]);

    // Assert
    expect(node.className).toBe('offscreen');
    expect(container.querySelector('.file-name')!.textContent).toBe(`${STEM}.fds`);
    expect(screen.getByText('Expects .fds, .qd').className).toBe('field-help quiet');
  });

  it('offers several files for a many-file field', () => {
    // Arrange
    const container = host(LINT);

    // Act
    const node = control(container, 'others');

    // Assert
    expect(node.multiple).toBe(true);
    expect(node.closest('label')!.querySelector('.file-button')!.textContent).toBe('Choose files');
    expect(node.closest('label')!.querySelector('.file-name')!.textContent).toBe('No file chosen');
  });

  it('tells the visitor at once what is wrong with a value', () => {
    // Arrange
    const container = host();
    const node = control(container, 'passes');

    // Act
    fireEvent.input(node, { target: { value: '0' } });

    // Assert
    const label = node.closest('label')!;
    expect(label.querySelector('.field-problem')!.textContent).toBe('Must be 1 or more.');
    expect(label.className).toBe('field missing');
  });

  it('draws a box as a missing field when told so, and reports an edit', async () => {
    // Arrange
    const edited = vi.fn();
    const field = INFO.fields[0]!;
    const { container } = render(<FieldControl spec={field} command="info" missing onEdited={edited} />);
    const node = control(container, 'data');

    // Act
    await choose(node, [new File([new Uint8Array([1])], `${STEM}.fds`)]);

    // Assert
    expect(node.closest('label')!.className).toBe('field missing');
    expect(edited).toHaveBeenCalledWith('data');
  });

  it('puts a flag beside its caption', () => {
    // Arrange
    const container = host();

    // Act
    const label = control(container, 'formatted').closest('label')!;

    // Assert
    expect(label.className).toBe('field checkbox');
    expect(label.querySelector('.checkbox-line > input')).toBe(control(container, 'formatted'));
  });
});

describe('problemFor', () => {
  it('says nothing about a valid value', () => {
    // Arrange
    const node = { checkValidity: () => true, validity: {} as ValidityState, validationMessage: '' };

    // Act
    const result = problemFor(node, BOUNDED, english);

    // Assert
    expect(result).toBe('');
  });

  it('names each limit a value breaks', () => {
    // Arrange
    const cases = [
      checkable({ rangeOverflow: true }),
      checkable({ tooShort: true }),
      checkable({ tooLong: true }),
      checkable({ badInput: true }),
      checkable({ valueMissing: true }),
      checkable({}, 'browser says no'),
    ];

    // Act
    const result = cases.map((node) => problemFor(node, BOUNDED, english));

    // Assert
    expect(result).toEqual([
      'Must be 9 or less.',
      'Needs at least 3 characters.',
      'No more than 4 characters.',
      'That is not the shape this field expects.',
      'This one is required.',
      'browser says no',
    ]);
  });
});

describe('collect', () => {
  it('types every value and leaves out what is empty', async () => {
    // Arrange
    const container = host();
    fireEvent.change(control(container, 'game_name'), { target: { value: 'ABC' } });
    fireEvent.change(control(container, 'sides'), { target: { value: '2' } });

    // Act
    const body = await collect(container, BLANK);

    // Assert
    expect(body).toEqual({ sides: 2, passes: 1, formatted: true, game_name: 'ABC' });
  });

  it('encodes chosen files and names the output after the first one', async () => {
    // Arrange
    const container = host(INFO);
    await choose(control(container, 'data'), [new File([new Uint8Array([1, 2])], `${STEM}.qd`)]);

    // Act
    const body = await collect(container, INFO);

    // Assert
    expect(body).toEqual({ data: 'AQI=', name: `${STEM}.fds` });
  });

  it('sends every file of a many-file field and the default name when none was chosen', async () => {
    // Arrange
    const container = host(LINT);
    await choose(control(container, 'others'), [
      new File([new Uint8Array([1])], `${STEM}.fds`),
      new File([new Uint8Array([2])], `${OTHER_STEM}.fds`),
    ]);

    // Act
    const body = await collect(container, LINT);

    // Assert
    expect(body).toEqual({ others: ['AQ==', 'Ag=='], report: `${STEM}.json` });
  });

  it('leaves out a file field nobody chose and a field the page does not draw', async () => {
    // Arrange
    const container = host(WRITE);

    // Act
    const body = await collect(container, WRITE);

    // Assert
    expect(body).toEqual({});
  });

  it('refuses a form whose controls are not on the page', async () => {
    // Arrange
    const empty = document.createElement('div');

    // Act
    const collecting = collect(empty, BLANK);

    // Assert
    await expect(collecting).rejects.toThrow('the page lost the control for sides');
  });
});

describe('missingIn', () => {
  it('names the required fields left empty', () => {
    // Arrange
    const container = host(INFO);

    // Act
    const result = missingIn(container, INFO);

    // Assert
    expect(result).toEqual(['data']);
  });

  it('names nothing once every required field is filled', () => {
    // Arrange
    const container = host();
    fireEvent.change(control(container, 'game_name'), { target: { value: 'ABC' } });

    // Act
    const result = missingIn(container, BLANK);

    // Assert
    expect(result).toEqual([]);
  });
});

describe('invalidIn', () => {
  it('gives the reason for every value out of range', () => {
    // Arrange
    const container = host();
    fireEvent.change(control(container, 'passes'), { target: { value: '25' } });

    // Act
    const result = invalidIn(container, BLANK, english);

    // Assert
    expect(result).toEqual(['passes: Must be 20 or less.', 'game name: This one is required.']);
  });

  it('skips the fields the page does not draw', () => {
    // Arrange
    const container = host(formOf({ command: 'x', family: 'y', fields: [fieldOf({ name: 'hidden', kind: 'flag', hidden: true })] }));

    // Act
    const result = invalidIn(container, WRITE, english);

    // Assert
    expect(result).toEqual([]);
  });
});

describe('chosenFiles', () => {
  it('answers no files for a control that holds none', () => {
    // Arrange
    const node = { files: null };

    // Act
    const result = chosenFiles(node);

    // Assert
    expect(result).toEqual([]);
  });
});
