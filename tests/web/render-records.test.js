import { beforeEach, describe, expect, it } from 'vitest';

import {
  describe as describeValue,
  isChange,
  isProse,
  renderResult,
} from '../../src/fdstoolkit/ui/static/render.js';

let target;

beforeEach(() => {
  target = document.createElement('div');
});

const SIDE = {
  index: 0,
  origin: 'rewritten',
  notes: ['the captures show a side written in one stream', 'its data fields still say factory'],
  signature: null,
};

describe('records that carry prose', () => {
  it('renders a card per record rather than a table', () => {
    // Arrange
    const records = [SIDE, { ...SIDE, index: 1 }];

    // Act
    const node = describeValue(records);

    // Assert
    expect(node.querySelector('table')).toBeNull();
    expect(node.querySelectorAll('.change')).toHaveLength(2);
  });

  it('gives every sentence of a list its own line', () => {
    // Arrange
    const records = [SIDE];

    // Act
    const node = describeValue(records);

    // Assert
    expect([...node.querySelectorAll('.change-note')].map((n) => n.textContent)).toEqual(SIDE.notes);
  });

  it('keeps the short values as chips', () => {
    // Arrange
    const expected = [
      'index',
      'origin',
      'signature',
    ];

    // Act
    const node = describeValue([SIDE]);

    // Assert
    expect([...node.querySelectorAll('.chip-key')].map((n) => n.textContent)).toEqual(expected);
  });

  it('leaves out a list with nothing in it', () => {
    // Arrange
    const expected = 'notes';

    // Act
    const node = describeValue([{ ...SIDE, notes: [], note: 'one long sentence here' }]);

    // Assert
    expect(node.textContent).not.toContain(expected);
  });
});


const CHANGE = {
  side: 0,
  field: 'game_name',
  description: 'three-letter game code',
  identity: true,
  left: 'SMB',
  right: 'ZLD',
};

describe('change records', () => {
  it('renders a before and after rather than a row of columns', () => {
    // Arrange
    const records = [CHANGE];

    // Act
    const node = describeValue(records);

    // Assert
    expect(node.querySelector('table')).toBeNull();
    expect(node.querySelectorAll('.change')).toHaveLength(1);
  });

  it('puts the two values side by side under their own labels', () => {
    // Arrange
    const node = describeValue([CHANGE]);

    // Act
    const sides = [...node.querySelectorAll('.side-value')].map((cell) => cell.textContent);

    // Assert
    expect(sides).toEqual(['SMB', 'ZLD']);
  });

  it('keeps prose out of the chips and gives it its own line', () => {
    // Arrange
    const expected = 'three-letter game code';

    // Act
    const node = describeValue([CHANGE]);

    // Assert
    expect(node.querySelector('.change-note').textContent).toBe(expected);
    expect([...node.querySelectorAll('.chip-key')].map((n) => n.textContent)).toEqual([
      'side',
      'field',
    ]);
  });

  it('shows a true flag as its name alone, with no yes beside it', () => {
    // Arrange
    const expected = 'identity';

    // Act
    const node = describeValue([CHANGE]);

    // Assert
    expect(node.querySelector('.chip-flag').textContent).toBe(expected);
    expect(node.textContent).not.toContain('yes');
  });

  it('leaves a false flag out entirely', () => {
    // Arrange
    const records = [{ ...CHANGE, identity: false }];

    // Act
    const node = describeValue(records);

    // Assert
    expect(node.querySelector('.chip-flag')).toBeNull();
    expect(node.textContent).not.toContain('identity');
  });

  it('takes the full width so the values are never squeezed', () => {
    // Arrange
    const records = [CHANGE];

    // Act
    const node = describeValue(records);

    // Assert
    expect(node.classList.contains('wide')).toBe(true);
  });
});

describe('shape tests', () => {
  it('reads a record carrying both ends as a change', () => {
    // Arrange
    const expected = true;

    // Act
    const result = isChange([CHANGE]);

    // Assert
    expect(result).toBe(expected);
    expect(isChange([{ side: 0, block: 0 }])).toBe(false);
  });

  it('treats a phrase as prose and a token as a chip', () => {
    // Arrange
    const expected = true;

    // Act
    const result = isProse('three-letter game code');

    // Assert
    expect(result).toBe(expected);
    expect(isProse('game_name')).toBe(false);
    expect(isProse(0)).toBe(false);
  });
});

describe('wide values', () => {
  it('lifts the label onto its own line so a table gets the whole column', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { rows: [{ a: 1, b: 2, c: 3 }] });

    // Assert
    expect(target.querySelector('dt').classList.contains('wide')).toBe(true);
  });

  it('leaves a short value beside its label', () => {
    // Arrange
    const target = document.createElement('div');

    // Act
    renderResult(target, { grade: 'clean' });

    // Assert
    expect(target.querySelector('dt').classList.contains('wide')).toBe(false);
  });
});
