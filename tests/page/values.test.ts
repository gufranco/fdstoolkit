import { describe, expect, it } from 'vitest';

import { translate } from '../../web/src/i18n';
import type { FormField } from '../../web/src/schemas';
import {
  bytes,
  describeLimits,
  helpFor,
  isChange,
  isDownload,
  isProse,
  isRecord,
  named,
  orderFamilies,
  scalar,
  sentence,
  typed,
  words,
} from '../../web/src/values';
import { fileStems, gameNames, seeded } from './fakes';

const FAKE = seeded('values.test');
const [GAME = ''] = gameNames(FAKE, 1);
const [STEM = '', OTHER_STEM = '', THIRD_STEM = '', FOURTH_STEM = ''] = fileStems(FAKE, 4);
const english = (key: string): string => translate('en', key);

function field(overrides: Partial<FormField>): FormField {
  return {
    name: 'passes',
    kind: 'number',
    required: false,
    accepts: '',
    default: null,
    options: [],
    minimum: null,
    maximum: null,
    step: null,
    min_length: null,
    max_length: null,
    hidden: false,
    ...overrides,
  };
}

describe('named', () => {
  it('keeps the chosen name when it already carries the wanted suffix', () => {
    // Arrange
    const expected = `${STEM}.fds`;

    // Act
    const result = named(`${STEM}.fds`, 'disk.fds');

    // Assert
    expect(result).toBe(expected);
  });

  it('swaps a suffix the command does not produce', () => {
    // Arrange
    const expected = `${OTHER_STEM}.fds`;

    // Act
    const result = named(`${OTHER_STEM}.json`, 'disk.fds');

    // Assert
    expect(result).toBe(expected);
  });

  it('adds the suffix when the chosen name carries none', () => {
    // Arrange
    const expected = `${THIRD_STEM}.fds`;

    // Act
    const result = named(THIRD_STEM, 'disk.fds');

    // Assert
    expect(result).toBe(expected);
  });

  it('falls back to the schema default when nothing was chosen', () => {
    // Arrange
    const expected = 'disk.fds';

    // Act
    const result = named('', 'disk.fds');

    // Assert
    expect(result).toBe(expected);
  });

  it('keeps the chosen name when the default carries no suffix', () => {
    // Arrange
    const expected = `${STEM}.fds`;

    // Act
    const result = named(`${STEM}.fds`, null);

    // Assert
    expect(result).toBe(expected);
  });
});

describe('bytes', () => {
  it('reports small sizes in bytes', () => {
    // Arrange
    const expected = '512 B';

    // Act
    const result = bytes(512);

    // Assert
    expect(result).toBe(expected);
  });

  it('reports a two-side image in kibibytes', () => {
    // Arrange
    const expected = '127.9 KiB';

    // Act
    const result = bytes(131000);

    // Assert
    expect(result).toBe(expected);
  });
});

describe('scalar', () => {
  it('names an absent value rather than printing null', () => {
    // Arrange
    const expected = ['none', 'none'];

    // Act
    const result = [scalar(null, english), scalar(undefined, english)];

    // Assert
    expect(result).toEqual(expected);
  });

  it('spells booleans out', () => {
    // Arrange
    const expected = ['yes', 'no'];

    // Act
    const result = [scalar(true, english), scalar(false, english)];

    // Assert
    expect(result).toEqual(expected);
  });

  it('passes numbers and text through', () => {
    // Arrange
    const expected = ['0', 'clean'];

    // Act
    const result = [scalar(0, english), scalar('clean', english)];

    // Assert
    expect(result).toEqual(expected);
  });
});

describe('words', () => {
  it('turns a field name into something readable', () => {
    // Arrange
    const expected = 'bad blocks';

    // Act
    const result = words('bad_blocks');

    // Assert
    expect(result).toBe(expected);
  });
});

describe('sentence', () => {
  it('starts a detail with a capital', () => {
    // Arrange
    const expected = 'None connected at 16D0:0AAA';

    // Act
    const result = sentence('none connected at 16D0:0AAA');

    // Assert
    expect(result).toBe(expected);
  });
});

describe('isDownload', () => {
  it('accepts an entry carrying bytes, a size and a name', () => {
    // Arrange
    const entry = { data: 'AA==', size: 1, name: `${FOURTH_STEM}.fds` };

    // Act
    const result = isDownload(entry);

    // Assert
    expect(result).toBe(true);
  });

  it('refuses a list of disk files, which carry no bytes', () => {
    // Arrange
    const entry = { name: GAME, size: 4096 };

    // Act
    const result = isDownload(entry);

    // Assert
    expect(result).toBe(false);
  });

  it('refuses nothing at all', () => {
    // Arrange
    const entry = null;

    // Act
    const result = isDownload(entry);

    // Assert
    expect(result).toBe(false);
  });
});

describe('isRecord', () => {
  it('tells an object from a list and from nothing', () => {
    // Arrange
    const values = [{ side: 0 }, [1], null, 'text'];

    // Act
    const result = values.map(isRecord);

    // Assert
    expect(result).toEqual([true, false, false, false]);
  });
});

describe('isChange', () => {
  it('sees rows that each carry a left and a right', () => {
    // Arrange
    const rows = [{ left: GAME, right: 'x' }, { left: 1, right: 2, side: 0 }];

    // Act
    const result = isChange(rows);

    // Assert
    expect(result).toBe(true);
  });

  it('refuses rows where one carries no right', () => {
    // Arrange
    const rows = [{ left: GAME, right: 'x' }, { left: 1 }];

    // Act
    const result = isChange(rows);

    // Assert
    expect(result).toBe(false);
  });
});

describe('isProse', () => {
  it('takes text with a space or a long text as prose', () => {
    // Arrange
    const values = ['the block failed', 'x'.repeat(25), 'clean', 7];

    // Act
    const result = values.map(isProse);

    // Assert
    expect(result).toEqual([true, true, false, false]);
  });
});

describe('describeLimits', () => {
  it('states a range when both ends are known', () => {
    // Arrange
    const expected = 'Between 1 and 8.';

    // Act
    const result = describeLimits(field({ minimum: 1, maximum: 8 }), english);

    // Assert
    expect(result).toBe(expected);
  });

  it('states a floor alone', () => {
    // Arrange
    const expected = '0 or more.';

    // Act
    const result = describeLimits(field({ minimum: 0 }), english);

    // Assert
    expect(result).toBe(expected);
  });

  it('states a ceiling alone', () => {
    // Arrange
    const expected = '65535 or less.';

    // Act
    const result = describeLimits(field({ maximum: 65535 }), english);

    // Assert
    expect(result).toBe(expected);
  });

  it('states an exact length when both lengths agree', () => {
    // Arrange
    const expected = 'Exactly 3 characters.';

    // Act
    const result = describeLimits(field({ min_length: 3, max_length: 3 }), english);

    // Assert
    expect(result).toBe(expected);
  });

  it('states a maximum length', () => {
    // Arrange
    const expected = 'Up to 8 characters.';

    // Act
    const result = describeLimits(field({ max_length: 8 }), english);

    // Assert
    expect(result).toBe(expected);
  });

  it('says nothing when the field is unbounded', () => {
    // Arrange
    const expected = '';

    // Act
    const result = describeLimits(field({}), english);

    // Assert
    expect(result).toBe(expected);
  });
});

describe('typed', () => {
  it('sends a choice on a whole-number field as a number', () => {
    // Arrange
    const expected = 2;

    // Act
    const result = typed('choice', '2', true);

    // Assert
    expect(result).toBe(expected);
  });

  it('keeps a choice on a text field as text', () => {
    // Arrange
    const expected = 'release';

    // Act
    const result = typed('choice', 'release', false);

    // Assert
    expect(result).toBe(expected);
  });

  it('sends a number field as a number', () => {
    // Arrange
    const expected = 3;

    // Act
    const result = typed('number', '3', false);

    // Assert
    expect(result).toBe(expected);
  });

  it('keeps a text field as text', () => {
    // Arrange
    const expected = '12';

    // Act
    const result = typed('text', '12', false);

    // Assert
    expect(result).toBe(expected);
  });

  it('leaves an empty value out of the request', () => {
    // Arrange
    const value = '';

    // Act
    const result = typed('choice', value, true);

    // Assert
    expect(result).toBeUndefined();
  });
});

describe('orderFamilies', () => {
  it('keeps the order the catalogue declares', () => {
    // Arrange
    const expected = ['inspect', 'check', 'hardware'];

    // Act
    const result = orderFamilies(['hardware', 'check', 'inspect'], ['inspect', 'check', 'hardware']);

    // Assert
    expect(result).toEqual(expected);
  });

  it('puts a family the catalogue does not name last', () => {
    // Arrange
    const expected = ['inspect', 'other'];

    // Act
    const result = orderFamilies(['other', 'inspect'], ['inspect']);

    // Assert
    expect(result).toEqual(expected);
  });

  it('falls back to alphabetical order with no declared order', () => {
    // Arrange
    const expected = ['check', 'repair'];

    // Act
    const result = orderFamilies(['repair', 'check'], []);

    // Assert
    expect(result).toEqual(expected);
  });
});

describe('helpFor', () => {
  it('prefers the help a command gives its own field', () => {
    // Arrange
    const expected = 'read each side';

    // Act
    const result = helpFor('dump', field({ name: 'passes' }), english);

    // Assert
    expect(result).toContain(expected);
  });

  it('falls back to the help the field shares', () => {
    // Arrange
    const expected = 'run all four patterns';

    // Act
    const result = helpFor('surface', field({ name: 'passes' }), english);

    // Assert
    expect(result).toContain(expected);
  });
});
