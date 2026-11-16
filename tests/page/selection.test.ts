import { describe, expect, it } from 'vitest';

import {
  familiesOf,
  NOTHING_SELECTED,
  select,
  selectedForm,
  visible,
} from '../../web/src/selection';
import { CATALOGUE, FORMS } from './harness';

const BLANK = FORMS[2]!;
const DUMP = FORMS[4]!;

describe('familiesOf', () => {
  it('orders the families the catalogue declares and puts the rest last', () => {
    // Arrange
    const expected = ['inspect', 'repair', 'container', 'hardware', 'check', 'elsewhere'];

    // Act
    const result = familiesOf(FORMS, CATALOGUE.families);

    // Assert
    expect(result).toEqual(expected);
  });
});

describe('select', () => {
  it('shows the command the address names', () => {
    // Arrange
    const action = { type: 'show', wanted: 'dump', forms: FORMS } as const;

    // Act
    const result = select(NOTHING_SELECTED, action);

    // Assert
    expect(result).toEqual({ filter: '', family: 'hardware', command: 'dump' });
  });

  it('shows the first command when the address names none it knows', () => {
    // Arrange
    const action = { type: 'show', wanted: 'nothing', forms: FORMS } as const;

    // Act
    const result = select(NOTHING_SELECTED, action);

    // Assert
    expect(result).toEqual({ filter: '', family: 'inspect', command: 'info' });
  });

  it('keeps the selection when the catalogue is empty', () => {
    // Arrange
    const action = { type: 'show', wanted: 'dump', forms: [] } as const;

    // Act
    const result = select(NOTHING_SELECTED, action);

    // Assert
    expect(result).toBe(NOTHING_SELECTED);
  });

  it('moves to a family, its first command, and clears the filter', () => {
    // Arrange
    const start = { filter: 'bl', family: 'container', command: 'blank' };

    // Act
    const result = select(start, { type: 'family', first: DUMP });

    // Assert
    expect(result).toEqual({ filter: '', family: 'hardware', command: 'dump' });
  });

  it('picks a command and its family', () => {
    // Arrange
    const start = { filter: 'b', family: 'inspect', command: 'info' };

    // Act
    const result = select(start, { type: 'command', form: BLANK });

    // Assert
    expect(result).toEqual({ filter: 'b', family: 'container', command: 'blank' });
  });

  it('filters by name and selects the first match', () => {
    // Arrange
    const action = { type: 'filter', text: ' DU ', forms: FORMS } as const;

    // Act
    const result = select(NOTHING_SELECTED, action);

    // Assert
    expect(result).toEqual({ filter: ' DU ', family: 'hardware', command: 'dump' });
  });

  it('keeps the command when nothing matches the filter', () => {
    // Arrange
    const start = { filter: '', family: 'inspect', command: 'info' };

    // Act
    const result = select(start, { type: 'filter', text: 'zz', forms: FORMS });

    // Assert
    expect(result).toEqual({ filter: 'zz', family: 'inspect', command: 'info' });
  });
});

describe('visible', () => {
  it('lists the family when there is no filter', () => {
    // Arrange
    const selection = { filter: '', family: 'hardware', command: 'dump' };

    // Act
    const result = visible(selection, FORMS).map((form) => form.command);

    // Assert
    expect(result).toEqual(['status', 'dump', 'write']);
  });
});

describe('selectedForm', () => {
  it('finds the form of the selected command or nothing', () => {
    // Arrange
    const chosen = { filter: '', family: 'container', command: 'blank' };

    // Act
    const result = [selectedForm(chosen, FORMS), selectedForm(NOTHING_SELECTED, FORMS)];

    // Assert
    expect(result).toEqual([BLANK, undefined]);
  });
});
